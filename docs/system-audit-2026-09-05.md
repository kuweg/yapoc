# YAPOC runtime and recovery audit — 2026-09-05

The reported master stalls and post-restart chat routing failures are patched in the working tree. The follow-up also addresses the notification, provider termination, recovery, scheduling, Git ownership, and access-control findings below. Existing unrelated changes were preserved.

Scope: source review and isolated failure simulation of master/tool execution, task dispatch, restart context, notification delivery, browser state, provider streams, startup cleanup, Git checkpoints, and HTTP/WebSocket access. This is not a live provider/restart certification or an exhaustive security audit.

## Corrections

| Finding | Implemented behavior |
| --- | --- |
| Master announces an action but exits successfully | Expanded the English announcement detector to cover “I am going to”, typographic apostrophes, and filenames containing periods. Actual tool execution resets consecutive retries. Two unsuccessful recovery nudges produce an explicit incomplete-task error. Conditional sign-offs are excluded. |
| Guard exits masquerade as success | Missing completion events, unsupported provider stop reasons, empty initial output, budget stops, persistent tool loops, and exhausted turn limits now fail explicitly. Cancellation preserves partial output. Per-run loop state resets; runners use centralized turn limits. |
| Adapters manufacture completion after truncation | OpenAI, OpenRouter, DeepSeek, Moonshot, LM Studio, Codex, Ollama, and Google tool streams require explicit successful termination. Failed/incomplete/filtered/token-limited responses propagate errors. Malformed tool arguments are rejected rather than replaced with empty objects. BaseAgent validates Anthropic's native stop reason before executing calls. Streamed assistant text is retained in working history. |
| Restart loses context or conversation ownership | Explicit browser session IDs are retained without requiring CLI history files. No latest-session guessing. The real working transcript is snapshotted before restart. Multiline resume fields are JSON-encoded and atomically written. Startup restores context and uses a deterministic resume ID. Originating runs are superseded when an explicit resume takes over. |
| Resumed output appears in a task card or another chat | Owned results append as ordinary assistant messages to their originating session, including inactive chats. Live autonomous output is filtered by session. Initial delegation replies also stay in normal chat. Sessionless/service work remains in Tasks/Notifications. Persisted completion IDs prevent duplicate append while retained in history. |
| Live feed stops advancing or loses text | Ring-buffer tracking follows event identity rather than array length. Subscriptions are reference counted. Raw transcript conversion preserves spaces and separates thinking, answers, and tool results; snapshot/live overlap is deduplicated. Agent events include session IDs. |
| Notifications are consumed before the model succeeds | The JSON queue is now a durable outbox. Stable IDs create delivery runs in SQLite without consuming inputs. Only persisted successful output acknowledges the exact input snapshot. Late arrivals remain pending. Persistence failures propagate; a later poll reconciles success if acknowledgment failed. Child runners also snapshot inputs instead of draining them before execution. |
| Completed planning cannot trigger execution | Completed plans become `continuation` runs linked to the originating request, with specialist-spawn permission. Ordinary `notification` runs remain summary-only. Both retain restart restrictions. New child assignments/results carry parent request IDs rather than inferring ownership from the latest chat message. |
| Notification retries disappear or duplicate execution | Failed deliveries retain their inputs. Retries have distinct deterministic run IDs and a bounded attempt count, so the UI can show a subsequent success after an earlier failure. Recovery prompts require inspection of partial outcomes before repeating assignments. Cancellation of the originating request suppresses new deliveries. |
| Redis pending messages are stranded | The master watcher periodically claims pending entries, persists their payload before ACK, and retries failures. Consumer cleanup retains registrations with pending messages so reclamation remains possible. |
| SSE, CLI, and queued work have separate lifecycles | Browser and CLI submissions now use the durable task queue. SSE reads ordered SQLite events; disconnecting closes the view without owning execution. Browser reattachment keeps the task ID and event cursor. CLI reattachment keeps its task ID. Stop requests backend cancellation. Shutdown records interrupted runs before closing shared services. |
| Lock waiters block foreground scheduling | Dispatcher starts one master run at a time, marks a row running only when acquired, and prioritizes UI/CLI/Telegram/resume work over queued background work. A conditional SQL claim prevents acquiring the same pending row twice. Background runs have a configurable time limit. Live executions are excluded from orphan timeout sweeps; zero disables the relevant timeout. |
| Delivery-side errors overwrite completed work | Persisted success remains success if notification acknowledgment or later bookkeeping fails. Such failures cannot cause the completed master work to be retried automatically. |
| Startup destroys unfinished child assignments | Startup journals the original task and process status before cleanup, verifies runner command/agent/project identity before signalling a PID, and preserves unfinished tasks with explicit `interrupted` state. Per-run tool checkpoints and original prompts inform recovery; uncertain tool outcomes are treated as unknown. |
| Shared-workspace Git operations can overwrite others' edits | Automatic commit and rollback now refuse shared-workspace ownership. Verification remains available. Refused checkpoints are retained, and replacement handles archive their predecessors. This deliberately disables unsafe mutation; it does not implement isolated worktrees. |
| Backend APIs and files assume trusted callers | Default bind is loopback. Unconfigured API access requires local peer/Host/Origin and conservative proxy checks. Configured remote access requires a bearer token or authenticated browser cookie; WebSockets share this boundary. Existing admin/webhook secrets remain independent. Browser login gates workspace mounting. File containment uses resolved path ancestry, excludes common secret files and Git internals, and avoids symlink traversal in the tree. Session path IDs are validated. |

## Configuration and activation

The running backend was not restarted and the production frontend was not replaced during verification. Restart the backend and rebuild/reload the frontend used by the browser to activate these changes. The CLI now requires the backend for master execution.

New settings are documented in `.env.example`:

- `HOST=127.0.0.1` by default. Existing explicit binds are not overwritten.
- `BACKEND_API_TOKEN`: empty permits local callers only. Remote deployments need a token, an explicit bind, and HTTPS at the deployment proxy. API/CLI clients send Bearer authentication; the browser offers token login and uses an HttpOnly cookie.
- `AUTONOMOUS_RUN_TIMEOUT=300`: seconds per background master run; zero disables this bound. Foreground runs keep their agent timeout and explicit cancellation.
- `NOTIFICATION_MAX_ATTEMPTS=3`, `NOTIFICATION_RETRY_SECONDS=30`: bounded delivery retries.

## Validation

Verification used mock providers/transports and temporary files/databases. No real model calls, agent spawns, external messages, backend restart, or Git mutation were performed. Temporary harnesses were used rather than adding repository tests, following the repository guidance.

Passed checks:

- Tool loop: announcement variants and exclusions, recovery followed by a real tool call, repeated-announcement failure, missing completion, provider output limit, turn exhaustion, per-run state reset, browser session ownership.
- Provider wire formats: normal completion, missing/failed/incomplete termination, token/filter stops, valid and malformed arguments across the changed adapters. Google STOP/MAX_TOKENS/SAFETY/missing-terminator cases passed separately.
- Durable dispatch: dropped SSE view, same-run reattachment, ordered cursor replay, single execution, foreign-session rejection, exact notification acknowledgment, disk failure, late arrivals, duplicate result delivery, bounded distinct retries, post-success bookkeeping failure, active cancellation, and graceful shutdown interruption.
- Recovery: multiline resume including a delimiter line, full transcript restoration beyond 4,000 characters, idempotent enqueue, child assignment journal, unrelated PID protection, Redis ACK only after persistence, and preservation of pending consumers.
- ASGI access checks passed for local/remote callers, token login, HttpOnly cookies, cross-origin requests, and rejected WebSocket connections. CLI rendering checks confirmed backend SSE task/session identity.
- Access/file/Git helpers: local and remote peer checks, bearer/cookie validation, Origin and forwarded-client restrictions, sibling-path escape and secret-file rejection, and refusal of Git mutation without invoking Git.
- Browser logic: queued completion delivery, reconnect recovery, duplicate suppression, inactive-session routing, persisted delivery IDs, reference-counted subscriptions, raw transcript conversion, SSE task/cursor preservation, and abort-listener cleanup.
- Python compilation and TypeScript checks passed. Production Vite build passed in `/tmp/yapoc-fixes-build`; the existing approximately 2.9 MB JavaScript bundle-size warning remains. Changed source files passed whitespace checks.

## Remaining limits

- Announcement detection is an English-language heuristic, not proof of semantic task completion.
- Tool side effects are not exactly-once across a crash. Recovery preserves evidence and asks the agent to inspect uncertain outcomes. It cannot prove whether an external action completed without an idempotency key or a tool-specific receipt.
- One backend process is the supported master owner. The queue claim protects individual rows; this does not establish distributed leadership across multiple backend instances.
- Cancelling a master run does not automatically terminate already-dispatched child processes. Interrupted children retain assignments for inspection/reassignment; they are not checkpointed at arbitrary Python instructions.
- Delivery retries stop at the configured limit and leave the input recoverable for operator action. Child-run acknowledgment after a crash can still result in repeated context delivery.
- Browser history remains bounded local storage, and WebSocket recovery uses a recent-task batch. This is not a server-backed, unlimited conversation archive. Ordered stream events currently require a future retention policy for long-running installations.
- Automatic shared-workspace Git commit/rollback is refused until reliable file ownership or isolated worktrees are implemented. This is an intentional capability reduction to preserve edits.
- Remote access is a single trusted-operator boundary, not tenant isolation or per-user authorization. End-to-end browser login/proxy and live restart acceptance still need verification in the deployed environment.

Deployment acceptance: start a task in chat A, open chat B, restart during A, verify continuation appears only in A as normal messages, reconnect/reload and verify no duplicate, then cancel a separate running master task and verify its durable status becomes `cancelled`.
