# YAPOC Master Agent & Multi-Agent Interaction - Solution Design

Based on the audit report (`docs/master-audit.md`), this document outlines the proposed architectural fixes and code changes to resolve the Master Agent idling, turn limitation, and queue delivery problems.

## 1. Preventing Master Agent from Idling (Redis Watcher Fixes)

**Problem:** Master permanently drops notifications when busy or errors occur because Redis messages are unconditionally ACKed. Startup sequences compete with active watchers.

**Proposed Fixes:**
*   **Do Not ACK on Busy:** In `app/backend/main.py` (`_process_inbox_message`), when `state == "running"`, the function should `return` **without** calling `_bus.stream_ack`. This leaves the message in the pending list for re-delivery on the next cycle, ensuring notifications are not lost.
*   **Fallback on Error:** In `app/backend/main.py` (`_master_redis_watcher`), if an exception is caught during task stream handling, the message should be enqueued into `notification_queue` as a fallback before ACKing it in Redis to ensure it can be processed later.
*   **Startup Sequence Ordering:** In `app/backend/main.py`, ensure `_startup_resume` finishes executing entirely *before* registering and starting `_master_redis_watcher` and `_master_notification_watcher`. This removes the startup race condition where watchers compete with the resume process.

## 2. Resolving Turn & Timeout Limitations

**Problem:** `notification_max_turns` is documented but missing. `task_timeout` (300s) acts as a hard ceiling for complex tasks.

**Proposed Fixes:**
*   **Implement `notification_max_turns`:** 
    *   Add `notification_max_turns: int = 3` to `app/config/settings.py`.
    *   In `app/agents/base/__init__.py`, conditionally check if the task body matches `[Process incoming notifications from sub-agents]`. If so, override `max_turns` with `settings.notification_max_turns` to enforce the documented behavior.
*   **Extend Timeout:** Update `task_timeout` in Master's `CONFIG.yaml` (or global `settings.py`) from `300` to `600` to give reasoning agents sufficient time, preventing premature termination while the chain timeout (`600s`) remains.

## 3. Fixing Dual Delivery & Queue Races

**Problem:** Notifications are delivered 2-3 times (`NotifyParentTool` fires Redis and Queue blindly). Watchers race and process duplicate messages. Queue vs `TASK.MD` states get out of sync.

**Proposed Fixes:**
*   **Conditional Fallback in `NotifyParentTool`:** Modify `app/utils/tools/delegation.py`. Attempt `bus.stream_add` to Redis first. Catch exceptions; if it fails, *then* call `notification_queue.enqueue`. Do not unconditionally enqueue to both. Ensure `runner._notify_parent_via_bus` follows this exact same pattern.
*   **Standardize Dedup Keys:** In `app/agents/base/runner.py` and `app/backend/services/notification_poller.py`, apply `.strip()` consistently to the result text so `notification_queue` deduplication accurately matches the string payload when comparing Redis vs Queue messages.
*   **Preemptive Queue Cleanup on Startup:** In `app/backend/main.py`'s `_startup_resume` phase, check loaded `notification_queue` entries against their corresponding `TASK.MD`'s `consumed_at` flag. If `consumed_at` is set, drain/remove the entry from the queue preemptively.
*   **Prevent Watcher Races:** Ensure that when `_master_redis_watcher` successfully processes a message, it explicitly drains the `notification_queue` of matching items to prevent `_master_notification_watcher` from picking up the fallback duplicate.