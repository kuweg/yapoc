# YAPOC Self-Evaluation Report

This file holds the evaluator agent's findings, newest at the top.
Each entry contains observations, identified issues, and proposed changes
for **human review** — nothing here has been applied automatically.

When you act on a proposal, leave a one-line edit under it noting what
happened (`> Applied 2026-05-18: edited X. Tested via Y. Result: Z.`).

---

## 2026-05-17 21:33 — Self-evaluation (round 8)

### Observations
- **Total spend**: $41.93 across 10 agents (423 tasks) — marginal increase from round 7 ($41.73)
- **Top spender**: master at $23.74 (57%) — structurally expected
- **Second spender**: builder at $13.22 (32%) — unchanged
- **Recent error count**: 16 — includes 2 DeepSeek 400 errors (master 16:34, builder 16:18) plus rollback test entries
- **Agents with health issues**: master (36), builder (26), planning (22), doctor (3) — master up from 32 in round 6
- **Active agents**: evaluator (running), master (idle) — all healthy
- **Tier 1 changes landed**: startup orphan cleanup, daily-budget halt, stuck detector — no regressions observed

### Top issues

1. **Fallback adapter mismatch — DeepSeek adapter receiving Anthropic model names** — Impact: HIGH
   Two 400 errors (master 16:34, builder 16:18) show `claude-haiku-4-5-20251001` being passed to the DeepSeek API, which rejects it. The error message says "The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed claude-haiku-4-5-20251001." This means the fallback routing logic is ignoring the `adapter` field on fallback entries and passing the model name to the primary adapter. Security's fallback chain has `{"adapter": "anthropic", "model": "claude-haiku-4-5-20251001"}` — if the primary DeepSeek call fails and the system tries this fallback but routes it through the DeepSeek adapter instead of Anthropic, it would produce exactly this error. This causes every fallback attempt to fail with a 400 error instead of gracefully switching providers.

2. **Librarian has zero fallback models** — Impact: MEDIUM
   `app/config/agent-settings.json` confirms librarian has no `fallbacks` key at all. If the primary model (`deepseek-chat`) fails or the DeepSeek API returns an error, the librarian's 20 tasks ($0.14 spend) fail with no recovery path. Every other agent has at least 2 fallbacks. This is a single point of failure.

3. **Builder's `codex` adapter in fallback chain may be unregistered** — Impact: MEDIUM
   Builder's fallback chain starts with `{"adapter": "codex", "model": "gpt-5.1-codex"}`. If `codex` is not a registered adapter in the system's adapter registry, this fallback will fail silently on every builder task that triggers a fallback. Combined with issue #1 (fallback routing ignoring adapter field), this could mean builder has effectively zero working fallbacks despite having 3 configured. Builder has 51 tasks and $13.22 spend — the second highest cost agent.

### Proposed changes (read-only — for human review)

1. **Target**: `app/agents/base/adapter.py` or fallback routing logic (wherever `_route_fallback` or equivalent lives)
   **Change**:
   ```
   # Current behavior (inferred from errors):
   # When a fallback is triggered, the model name is passed to the primary adapter
   # regardless of the fallback entry's "adapter" field.
   
   # Desired behavior:
   # When a fallback entry specifies "adapter": "anthropic", route the call
   # through the Anthropic adapter, not the primary DeepSeek adapter.
   ```
   **Why**: Two 400 errors (master 16:34, builder 16:18) confirm `claude-haiku-4-5-20251001` was passed to the DeepSeek API, which means the fallback routing is ignoring the adapter field and using the primary adapter instead.
   **Risk**: Fixing fallback routing could change behavior for all agents — test thoroughly. The fallback chain may intentionally use the primary adapter for some entries (e.g., planning's first fallback is `{"adapter": "deepseek", "model": "deepseek-v4-pro"}` — that one SHOULD use the DeepSeek adapter). The routing logic needs to respect the fallback entry's adapter, not blindly use the primary.

2. **Target**: `app/config/agent-settings.json` — librarian agent
   **Change**:
   ```
   "librarian": {
     "adapter": "deepseek",
     "model": "deepseek-chat",
     "temperature": 0.1,
     "max_tokens": 8096,
     "tools": [...],
     "delegation_targets": []
   }
   ↓
   "librarian": {
     "adapter": "deepseek",
     "model": "deepseek-chat",
     "temperature": 0.1,
     "max_tokens": 8096,
     "tools": [...],
     "delegation_targets": [],
     "fallbacks": [
       {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
       {"adapter": "openai", "model": "gpt-5.4-mini"}
     ]
   }
   ```
   **Why**: Librarian is the only agent with zero fallbacks — if the primary model fails, its 20 tasks fail with no recovery path. Every other agent has at least 2 fallbacks.
   **Risk**: Minimal — adding fallbacks only helps. However, if issue #1 (fallback adapter mismatch) is not fixed first, these fallbacks would also fail with 400 errors. Fix issue #1 first, then add librarian's fallbacks.

3. **Target**: `app/config/agent-settings.json` — builder agent's fallback chain
   **Change**:
   ```
   "fallbacks": [
     {"adapter": "codex", "model": "gpt-5.1-codex"},
     {"adapter": "openai", "model": "gpt-5.2"},
     {"adapter": "google", "model": "gemini-2.5-pro"}
   ]
   ↓
   "fallbacks": [
     {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
     {"adapter": "openai", "model": "gpt-5.4-mini"},
     {"adapter": "google", "model": "gemini-2.5-pro"}
   ]
   ```
   **Why**: The `codex` adapter with `gpt-5.1-codex` is not a standard adapter used by any other agent. If it's unregistered, builder's first fallback always fails, forcing it to the second or third fallback — adding latency on every builder task that needs a fallback. Replacing with `anthropic/claude-sonnet-4-6` (proven in master's and keeper's fallback chains) provides a reliable first fallback.
   **Risk**: If `codex` is a valid adapter that was intentionally configured, removing it loses that capability. Verify whether `codex` is registered before applying.

### Open questions
- Does the fallback routing logic actually respect the `adapter` field in fallback entries? The 400 errors suggest it doesn't — but this needs code inspection to confirm. The error at master 16:34 and builder 16:18 both show Claude models being passed to DeepSeek API.
- Is `deepseek-chat` a valid model name for the DeepSeek API? The error messages only show Claude models being rejected, not `deepseek-chat` itself. If `deepseek-chat` works, the primary model is fine and only fallback routing is broken.
- The rollback test errors (20:44, 20:47, 20:53) are labeled `ROLLBACK` with `reason='smoke test'` — these appear to be intentional tests of the new rollback machinery, not actual errors.

---

## 2026-05-17 21:24 — Self-evaluation (round 7)

### Observations
- **Total spend**: $41.73 across 10 agents (421 tasks) — marginal increase from round 6 ($41.18)
- **Top spender**: master at $23.68 (57%) — consistent, structurally expected
- **Second spender**: builder at $13.22 (32%) — unchanged
- **Recent error count**: 16 — includes 2 new DeepSeek 400 errors (master 16:34, builder 16:18) plus rollback test entries
- **Agents with health issues**: master (36), builder (26), planning (22), doctor (3) — master increased from 32 to 36 since round 6
- **Active agents**: evaluator (running), master (idle) — all healthy

### Top issues

1. **`deepseek-chat` model name likely invalid for DeepSeek API** — Impact: HIGH
   The DeepSeek API error at master 16:34 and builder 16:18 states: "The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed claude-haiku-4-5-20251001." While the immediate error is about a fallback model being routed to the wrong adapter, the primary model `deepseek-chat` used by 8 agents (master, builder, planning, keeper, librarian, evaluator, security, researcher) is also NOT in the valid set (`deepseek-v4-pro` or `deepseek-v4-flash`). If `deepseek-chat` is silently mapped or deprecated, every primary call may be failing and falling through to fallbacks — inflating cost and latency. The error feed shows these 400 errors recurring across rounds, suggesting the model name mismatch is unresolved.

2. **Librarian has zero fallback models** — Impact: MEDIUM
   `app/config/agent-settings.json` shows librarian with `"fallbacks": []` (no `fallbacks` key at all). If the primary model (`deepseek-chat`) fails or the DeepSeek API returns an error, the librarian has no fallback chain and the task fails hard. All other agents have at least 2 fallbacks. This is a single point of failure for the librarian's 20 tasks ($0.14 spend).

3. **Master health issues increased from 32 to 36** — Impact: LOW
   Master's health_issues count rose from 32 (round 6) to 36 (round 7). The new entries likely correspond to the rollback test errors (20:44, 20:47, 20:53) and the DeepSeek 400 error (16:34). These are expected operational events, not regressions, but the growing count should be monitored.

### Proposed changes (read-only — for human review)

1. **Target**: `app/config/agent-settings.json` — all agents using `deepseek` adapter
   **Change**:
   ```
   "model": "deepseek-chat"
   ↓
   "model": "deepseek-v4-pro"
   ```
   (Apply to master, builder, planning, keeper, librarian, evaluator, security, researcher — all 8 agents using `adapter: "deepseek"` with `model: "deepseek-chat"`)
   **Why**: The DeepSeek API error message explicitly states valid model names are `deepseek-v4-pro` or `deepseek-v4-flash`. Using `deepseek-chat` may cause silent fallthrough to fallbacks on every call, increasing cost and latency. The error at master 16:34 and builder 16:18 confirms the API rejects unrecognized model names.
   **Risk**: If `deepseek-chat` is actually a valid alias that DeepSeek accepts (the error was about a Claude model, not `deepseek-chat` itself), this change is unnecessary but harmless — `deepseek-v4-pro` is confirmed valid. Verify by checking if any tasks complete successfully on the primary model before applying.

2. **Target**: `app/config/agent-settings.json` — librarian agent
   **Change**:
   ```
   "librarian": {
     "adapter": "deepseek",
     "model": "deepseek-chat",
     "temperature": 0.1,
     "max_tokens": 8096,
     "tools": [...],
     "delegation_targets": []
   }
   ↓
   "librarian": {
     "adapter": "deepseek",
     "model": "deepseek-chat",
     "temperature": 0.1,
     "max_tokens": 8096,
     "tools": [...],
     "delegation_targets": [],
     "fallbacks": [
       {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
       {"adapter": "openai", "model": "gpt-5.4-mini"}
     ]
   }
   ```
   **Why**: Librarian is the only agent with zero fallbacks — if the primary model fails, its 20 tasks fail with no recovery path. Every other agent has at least 2 fallbacks.
   **Risk**: Minimal — adding fallbacks only helps. The Anthropic and OpenAI adapters are already proven in other agents' fallback chains.

3. **Target**: `app/agents/evaluator/REPORT.MD` — monitoring note
   **Change**: No config change needed. Monitor master's health_issues count. If it exceeds 40 without corresponding ERROR-level events, investigate whether the health tracking is double-counting or if there's a silent degradation.
   **Why**: Master's health_issues rose from 32 to 36 between rounds 6 and 7. The new entries correlate with rollback tests and historical DeepSeek errors, but sustained growth without resolution could indicate a tracking issue.
   **Risk**: None — this is a monitoring recommendation, not a code change.

### Open questions
- Does `deepseek-chat` actually work as a model name with the DeepSeek API, or does every primary call silently fail? The error feed shows 400 errors for `claude-haiku-4-5-20251001` (a fallback model), not for `deepseek-chat` itself. A test call with `deepseek-chat` vs `deepseek-v4-pro` would disambiguate.
- The rollback test errors (20:44, 20:47, 20:53) are labeled `ROLLBACK` level — are these expected smoke tests or actual failures? The labels `'rollback-test'` and `'smoke test'` suggest intentional testing.

---
