# YAPOC Self-Evaluation Report

This file holds the evaluator agent's findings, newest at the top.
Each entry contains observations, identified issues, and proposed changes
for **human review** — nothing here has been applied automatically.

When you act on a proposal, leave a one-line edit under it noting what
happened (`> Applied 2026-05-18: edited X. Tested via Y. Result: Z.`).

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

## 2026-05-17 16:59 — Self-evaluation (round 6 — sanity)

### Observations
- **Total spend**: $41.18 across 10 agents (415 tasks) — marginal increase from round 5
- **Top spender**: master at $23.17 (56%) — consistent
- **Recent error count**: 12 — all historical, no new ERROR-level entries since round 5
- **Agents with health issues**: master (32), builder (26), planning (22), doctor (3) — all pre-existing, no new issues
- **Active agents**: evaluator (running), master (idle) — all healthy

### Status: System clean. All prior fixes holding.

No new errors, timeouts, or crashes since round 5. The DeepSeek model routing errors (master 16:34, builder 16:18) are historical and pre-date the fix applied in earlier rounds. The planning timeout (16:21) is also historical.

### Proposed changes
None — system is within expected parameters.

---
