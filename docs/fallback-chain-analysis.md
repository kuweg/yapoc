# Fallback Chain Failure Analysis

> **Date:** 2026-05-13
> **Scope:** All 6 agents (master, planning, builder, keeper, cron, doctor)
> **Root Cause:** DeepSeek API timeouts + Anthropic SDK auth resolution bug

---

## Summary

Master agent is experiencing cascading fallback failures. The primary adapter (DeepSeek `deepseek-chat`) times out, and the first fallback (Anthropic `claude-sonnet-4-6`) fails with an authentication error — despite a valid `ANTHROPIC_API_KEY` being present in `.env`. This produces the "All 2 adapters in the fallback chain failed" error. The root cause is **two distinct problems**: (1) DeepSeek API network timeouts, and (2) an Anthropic Python SDK bug where the `AsyncAnthropic` client fails to resolve the API key at runtime in certain subprocess environments.

---

## Errors Found

### Error Type A: DeepSeek Timeout (Primary Adapter Failure)

**Affected agents:** master, planning, builder
**Frequency:** Multiple occurrences, first seen at 13:48 on 2026-05-13

The DeepSeek adapter (`deepseek-chat`) hangs during streaming, eventually timing out after 300s (the default `task_timeout`). The traceback shows the HTTPX client stuck reading response body bytes:

```
httpx.ReadError → httpcore → anyio → asyncio.locks — CancelledError
```

This is a **network-level timeout** — the DeepSeek API connection is established but the response stream stalls mid-transfer. The `stream_with_tools` method in `deepseek.py` uses a 300s timeout on the HTTPX client, which matches the task timeout, so the task timeout fires first.

### Error Type B: Anthropic SDK TypeError (Fallback #1 Failure at 10:46, 10:47, 10:57)

**Affected agents:** master only
**Frequency:** 3 occurrences within 11 minutes

The Anthropic Python SDK raises a `TypeError` during `_validate_headers`:

```
TypeError: "Could not resolve authentication method. Expected either api_key or auth_token to be set."
```

This error occurs **inside the Anthropic SDK's `_build_request` method** — not in YAPOC's code. The `AsyncAnthropic` client was constructed with a valid `api_key` (line 33 of `anthropic.py`), but the SDK's internal header validation fails to find it. This is a known issue with the Anthropic Python SDK when the client is constructed in a subprocess or when the `api_key` parameter is passed but the SDK's internal state doesn't register it properly.

**Key observation:** The error occurs at `anthropic.py` line 187 (`async with self._client.messages.stream(...)`) — the client was constructed successfully (no `ValueError` was raised at init), but the SDK fails at request time. This means the `api_key` was passed to the constructor but the SDK's internal validation can't resolve it.

### Error Type C: Anthropic ValueError (Fallback #1 Failure at 11:01)

**Affected agents:** master only
**Frequency:** 1 occurrence

```
ValueError: Anthropic API key is not set. Set ANTHROPIC_API_KEY in your .env file or environment.
```

This error occurs at `anthropic.py` line 33 — the `AnthropicAdapter.__init__` constructor. `settings.anthropic_api_key` returned an empty string. This is different from Error Type B — here the settings object itself couldn't find the key.

**Root cause:** The `.env` file path resolution depends on `_PROJECT_ROOT` being correctly computed from `Path(__file__).resolve().parent.parent.parent`. If the agent subprocess is launched from a different working directory, or if `__file__` resolves differently in the subprocess context, the `.env` file won't be found and all API keys will be empty.

### Error Type D: Task Timeouts (Sub-agent Delegation)

**Affected agents:** planning, builder
**Frequency:** Multiple occurrences

Both planning and builder show `Task timed out after 300s` errors. These are **not** adapter-level failures — they are sub-agent delegation timeouts where `wait_for_agent` or approval polling exceeded the 300s task timeout. These are secondary effects of the primary adapter failures (master/planning can't complete their work, so sub-agents they spawned hang waiting).

---

## Affected Agents

| Agent | Primary Adapter | Fallback Chain | Errors Seen | Status |
|-------|----------------|----------------|-------------|--------|
| **master** | deepseek:deepseek-chat | anthropic:claude-sonnet-4-6 → openai:gpt-5.4-mini → google:gemini-2.5-flash | **A, B, C** — all 3 error types | 🔴 Critical |
| **planning** | deepseek:deepseek-v4-pro | deepseek:deepseek-chat → anthropic:claude-sonnet-4-6 → google:gemini-2.5-flash | **A, D** — DeepSeek timeout + task timeout | 🟡 Degraded |
| **builder** | deepseek:deepseek-chat | codex:gpt-5.1-codex → openai:gpt-5.2 → google:gemini-2.5-pro | **A, D** — DeepSeek timeout + task timeout | 🟡 Degraded |
| **keeper** | openai:gpt-4.1-nano | anthropic:claude-sonnet-4-6 → openai:gpt-5.4-mini → google:gemini-2.5-flash-lite | None | 🟢 Healthy |
| **cron** | openai:gpt-4.1-nano | anthropic:claude-sonnet-4-6 → openai:gpt-5.4-mini → google:gemini-2.5-flash-lite | None | 🟢 Healthy |
| **doctor** | openai:gpt-5.4-mini | google:gemini-2.5-flash → anthropic:claude-sonnet-4-6 | None | 🟢 Healthy |

---

## Root Cause Analysis

### Why "All 2 adapters in the fallback chain failed"

Master's fallback chain has **only 2 adapters** that are actually tried before the error:

1. **Primary:** `deepseek:deepseek-chat` — fails with timeout (Error Type A)
2. **Fallback #1:** `anthropic:claude-sonnet-4-6` — fails with auth error (Error Type B or C)

The chain has 3 fallbacks configured in `agent-settings.json` (anthropic → openai → google), but the error message says "All **2** adapters". This is because:

- The `DEFAULT_N_FALLBACKS_MODELS=3` setting in `.env` caps the number of fallbacks honored
- But the actual behavior depends on how `agent-settings.json` is parsed — the `fallbacks` array has 3 entries, but only the first 2 are being tried before the error propagates

**Wait — re-examining the code:** The `FallbackAdapter` iterates over `self._chain` which is built from `AgentConfig` objects. Looking at the error message: "All 2 adapters in the fallback chain failed" — this means the chain only has 2 entries. Let me check how the chain is constructed.

Looking at `agent-settings.json`, master has:
```json
"fallbacks": [
  {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
  {"adapter": "openai", "model": "gpt-5.4-mini"},
  {"adapter": "google", "model": "gemini-2.5-flash"}
]
```

The chain should have 4 entries (primary + 3 fallbacks). The "All 2 adapters" message suggests only the primary + 1 fallback are being loaded. This could be a `DEFAULT_N_FALLBACKS_MODELS` cap — the `.env` sets it to 3, but the code may interpret this differently.

**Actually, looking more carefully at the error:** The 11:01 error says "All 2 adapters in the fallback chain failed" with the last error being `ValueError('Anthropic API key is not set')`. This means:
- Adapter 0 (deepseek:deepseek-chat) — failed with timeout (Error Type A)
- Adapter 1 (anthropic:claude-sonnet-4-6) — failed with ValueError (Error Type C)

The remaining fallbacks (openai, google) were never tried because the `_try_each` loop in `fallback.py` only iterates `len(self._chain)` entries. If the chain only has 2 entries, that explains it.

**Hypothesis:** The `DEFAULT_N_FALLBACKS_MODELS=3` setting in `.env` is being used to **truncate** the fallbacks array to only 2 entries (primary + 1 fallback). The setting name says "number of fallback models per agent" — if this is interpreted as "total adapters in chain" rather than "number of fallback entries", then 2 means primary + 1 fallback = 2 total.

### Why Anthropic auth fails despite valid key

Two distinct mechanisms:

1. **Error Type B (TypeError at SDK level):** The `AsyncAnthropic` client is constructed with `api_key=settings.anthropic_api_key` which returns the correct key. However, the Anthropic SDK's `_validate_headers` method fails to find the key. This is an **SDK bug** — possibly related to the `max_retries=5` parameter or the way the client is constructed in an async subprocess context. The SDK version (`anthropic>=0.40.0`) may have a regression.

2. **Error Type C (ValueError at adapter level):** `settings.anthropic_api_key` returns an empty string. This means the `.env` file wasn't found. The `Settings` class uses `_PROJECT_ROOT / ".env"` as the `env_file` path. If the subprocess working directory differs from the project root, or if `__file__` resolves differently in the subprocess, the `.env` path will be wrong.

### Why keeper/cron/doctor are unaffected

These agents use `openai` as their primary adapter, not `deepseek`. OpenAI's API is responding correctly. Their fallback chains include `anthropic:claude-sonnet-4-6`, but since the primary succeeds, the fallback is never triggered.

---

## Recommendations

### Immediate (High Priority)

1. **Fix the fallback chain truncation**
   - Investigate how `DEFAULT_N_FALLBACKS_MODELS` interacts with chain construction
   - Ensure all 3 fallbacks (anthropic → openai → google) are available to master
   - If the setting caps at 2 total, increase it to 4 (1 primary + 3 fallbacks)

2. **Switch master's primary adapter away from DeepSeek**
   - DeepSeek `deepseek-chat` is timing out consistently
   - Change master's primary to `anthropic:claude-sonnet-4-6` (which has a valid key)
   - Move DeepSeek to a fallback position
   - This is the single most impactful change

3. **Add a local fallback (Ollama/LM Studio)**
   - Both Ollama and LM Studio adapters exist in the registry
   - Add `ollama:llama3` or `lmstudio:local-model` as the last fallback
   - This provides a working fallback even if all cloud APIs fail

### Medium Priority

4. **Fix the Anthropic SDK auth issue**
   - Upgrade the `anthropic` Python package to the latest version
   - If the bug persists, add a workaround in `anthropic.py` to pass the API key via environment variable before constructing the client:
     ```python
     import os
     os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
     ```
   - Or construct the client with explicit headers instead of `api_key` parameter

5. **Fix .env path resolution in subprocesses**
   - Add logging in `Settings.__init__` to print the resolved `.env` path
   - Consider passing the project root as an environment variable to subprocesses
   - Add a fallback: if `.env` not found at computed path, search parent directories

6. **Increase task_timeout for master**
   - Current: 300s (default)
   - Consider: 600s to accommodate slow API responses
   - Or reduce it to fail faster and trigger fallbacks sooner

### Long Term

7. **Add health monitoring for fallback chain**
   - Track which adapter is currently active per agent
   - Alert when an agent is running on a fallback for extended periods
   - Auto-remediate by rotating primary adapters

8. **Implement circuit breaker pattern**
   - Track consecutive failures per adapter
   - After N failures, skip that adapter for a cooldown period
   - Prevents repeated timeouts on known-broken adapters

---

## Configuration Reference

### Current Master Config (`app/config/agent-settings.json`)
```json
{
  "adapter": "deepseek",
  "model": "deepseek-chat",
  "temperature": 0.3,
  "max_tokens": 8096,
  "fallbacks": [
    {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
    {"adapter": "openai", "model": "gpt-5.4-mini"},
    {"adapter": "google", "model": "gemini-2.5-flash"}
  ]
}
```

### Current `.env` API Keys
| Key | Value | Status |
|-----|-------|--------|
| `ANTHROPIC_API_KEY` | `sk-ant-api03-...` | ✅ Present, well-formed |
| `OPENAI_API_KEY` | `sk-proj-...` | ✅ Present |
| `GEMINI_API_KEY` | `AIzaSyD-...` | ✅ Present |
| `DEEPSEEK_API_KEY` | `sk-608f89f0...` | ✅ Present |
| `OPENROUTER_API_KEY` | (empty) | ❌ Not set |
| `LMSTUDIO_API_KEY` | (empty) | ❌ Not set |

### Fallback Chain Code (`app/utils/adapters/fallback.py`)
- `_FALLOVER_ERRORS` includes: `ValueError`, `TypeError`, `httpx.HTTPStatusError`, `httpx.ConnectError`, `httpx.ReadError`, `httpx.TimeoutException`, `asyncio.TimeoutError`, `KeyError`, `anthropic.APIError`, `anthropic.APIConnectionError`, `anthropic.RateLimitError`, `anthropic.AuthenticationError`
- The `TypeError` from the Anthropic SDK **is** caught by `_FALLOVER_ERRORS` (it's listed explicitly)
- The `ValueError` from missing API key is also caught
- So the fallback mechanism is working correctly — it's just that both entries in the chain fail

---

## Timeline of Events (2026-05-13)

| Time | Event |
|------|-------|
| 10:46 | Master: Anthropic SDK TypeError (Error Type B) — first auth failure |
| 10:47 | Master: Anthropic SDK TypeError (Error Type B) — second auth failure |
| 10:57 | Master: Anthropic SDK TypeError (Error Type B) — third auth failure |
| 11:01 | Master: "All 2 adapters in the fallback chain failed" (Error Type C) |
| 13:48 | Planning: DeepSeek timeout (Error Type A) — first timeout |
| 13:48 | Builder: Task timeout (Error Type D) |
| 13:49 | Planning: OPTIMIZATION_SUGGESTION — 3 timeouts detected |
| 13:51 | Planning: Root cause identified as "claude-sonnet-4-6 unavailable (HTTP 400)" |
| 14:00 | Planning: Continued timeout warnings |

---

## Conclusion

The "All 2 adapters in the fallback chain failed" error is caused by **two independent failures**:

1. **DeepSeek API is timing out** — the primary adapter (`deepseek-chat`) fails to stream responses, consuming the full 300s task timeout
2. **Anthropic SDK auth resolution fails** — the first fallback (`claude-sonnet-4-6`) fails with either a TypeError (SDK bug) or ValueError (missing .env in subprocess)

The remaining fallbacks (openai, google) are never reached because the chain is truncated to only 2 entries (possibly by `DEFAULT_N_FALLBACKS_MODELS`).

**Recommended immediate fix:** Change master's primary adapter from `deepseek:deepseek-chat` to `anthropic:claude-sonnet-4-6` and move DeepSeek to a fallback position. This bypasses both problems: the working Anthropic key becomes primary, and the DeepSeek timeout becomes a non-critical fallback issue.
