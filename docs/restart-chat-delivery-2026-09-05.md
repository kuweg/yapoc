# Restart reply missing from chat — 2026-09-05

## Confirmed cause

The screenshot's weather request was task `bc12ffb2-53ef-4af5-9f48-eeaec7f3e443`, owned by chat `2a37686e-2c59-451b-b143-727ce2d1e864`. The completed forecast was persisted as resume task `5e749d20-2db5-5965-959f-085cdea5b185`, whose session ID had incorrectly become that resume task's own ID.

The production tool factory in `app/utils/tools/__init__.py` passed `session_id` to delegation tools but omitted `server_restart`. The restart helper therefore wrote an empty session ID into RESUME.MD. Startup queued that sessionless resume, and the dispatcher substituted the new task ID as its session. AgentFlow could show the global agent activity, while ChatPanel correctly refused to append a result whose owner did not match any browser conversation.

The original task's persisted `server_restart` ToolStart event contains exactly the next action in the resumed prompt. This confirms lineage without using the latest chat or a timestamp guess. Backend logs and SQLite show successful completion; the model's decision to answer before restarting was not the cause of the missing post-restart reply.

Earlier helper tests missed the defect because they supplied the session ID directly instead of constructing the tool through `build_tools`.

## Changes

- The tool factory injects session ownership into `server_restart`.
- The restart writer and startup reader also recover ownership from the explicit originating task. This handles restart files produced by the old factory. New resume rows persist their origin ID in metadata.
- Dispatcher no longer invents chat IDs for unowned service work.
- WebSocket session subscription replays that conversation's recent task records, independently of the global recent-task batch.
- Browser deduplication permits a corrected owner after an earlier misrouted completion. Per-session delivery receipts survive display-history trimming, preventing replayed replies from being appended again after reload.

## Existing forecast repaired

The stored completed forecast was reassigned to its verified original chat. Its result and execution status were preserved; it was not re-executed. The original row was backed up to `/tmp/yapoc-weather-resume-owner-before.json`. Metadata records the explicit origin and exact-action matching used for repair.

## Verification

- `poetry run pytest -q tests/test_restart_chat_delivery.py`: **4 passed**; factory → restart-state writer → startup handoff → dispatcher → completion event → session snapshot; legacy empty-session recovery; authoritative origin fallback; service work stays sessionless.
- TypeScript check and production build passed. Build: `/tmp/yapoc-restart-build-final`. Existing bundle-size warning remains.
- `scripts/check_restart_chat_browser.py` uses installed Playwright/Chromium because Playwright MCP was not exposed. It tests the real built React application with intercepted backend traffic and a simulated WebSocket restart: lost completion replay, ordinary chat rendering, inactive-session ownership, reload deduplication, recovery beyond the global task batch, corrected ownership, and delivery receipts after history trimming.
- Browser evidence: `/tmp/yapoc-restart-chat-pass.png`.
- A separate Playwright check used read-only requests against the running UI at localhost:5173 in a fresh browser profile. It confirmed the actual repaired forecast appears in its original chat and remains single after reload and WebSocket reconnection. Screenshot: `/tmp/yapoc-live-weather-recovered.png`. No new task was submitted.

The simulated restart test does not call a live model, launch an agent, or restart the production service. Python tests exercise the real restart handoff with process signalling mocked. Backend source changes load on the next backend restart; Vite serves frontend source updates. Session replay remains bounded to recent records and is not an unlimited server-side conversation archive.

## Follow-up: actual restart through the browser

After the user explicitly requested a live restart test, two real master requests were submitted through the chat composer using installed Playwright/Chromium. The browser-act plugin was present, but its required `browser-act` CLI was missing (`command not found`), so the installed local browser automation was used instead. Each request instructed the master to restart exactly once and return a unique marker plus the result of `17 * 23` after restarting. Neither test manually repaired database ownership or injected a completion event.

| Run | Backend PID change | Original chat | Resume task | Result |
| --- | --- | --- | --- | --- |
| Before connection cleanup fix | 4050048 → 4064469 | cdf4d851-d047-4f72-a505-9b85589e3d42 | 95eca625-910d-55e6-983b-32babc4bd286 | Marker and 391 appeared in chat at ~37 seconds; once after reload |
| After connection cleanup fix | 4064469 → 4103403 | 4a1cd353-fa5c-4204-8bf9-5da53c69bad4 | dc23c45a-f795-5632-b2f4-57b04cffec07 | Marker and 391 appeared in chat at ~41 seconds; once after reload |

The previous session ownership fix therefore passes an actual process restart and model continuation. The restarted backend has loaded those source changes.

### Additional confirmed defect fixed

The live Vite UI opened two `/ws` connections for a single browser page. React StrictMode cleans up and remounts effects; the hook's shared `unmountedRef` became false again before the retired socket delivered its close callback. That stale callback cleared the current socket reference and scheduled another connection. Online/visibility retries also created additional sockets while a connection was still opening.

`useWebSocket.ts` now uses an effect-local disposal flag, rejects callbacks from non-current sockets, detaches handlers during cleanup, and skips new connections while the current socket is open or connecting.

`scripts/check_ws_lifecycle_browser.py` reproduces this in the real development UI without submitting tasks. Before the fix, socket states were `[3, 1, 1]` (two open). After the fix they were `[3, 1]`, and `[3, 3, 1]` after repeated online/reconnect triggers (one open). The second real restart also asserted one open task WebSocket after reload. This test exercises the development StrictMode lifecycle that the earlier production-build browser tests did not cover.

Validation: four backend regression tests passed again; TypeScript check passed; the lifecycle browser regression passed; both real restarts returned to the original chat. Evidence: `/tmp/yapoc-live-restart/final.png`, `/tmp/yapoc-live-restart-fixed/final.png`, with corresponding `events.jsonl` and `sessions.json` files in those directories. Browser tests used separate profiles, so their new test conversations do not appear in the user's browser-local chat list.

An unrelated configuration issue was also observed in backend logs: the master's primary `DeepSeek-V4-Pro-0813` was rejected with HTTP 400, then its configured `deepseek-v4-pro` fallback succeeded. That adds unnecessary provider failures to turns; this follow-up did not change model preferences.
