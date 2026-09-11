"""Task Dispatcher — background loop that polls task_queue and executes tasks.

Started as an asyncio task in main.py lifespan. Picks up pending tasks from
the SQLite task_queue, dispatches them, and writes results back. Handles
concurrency limits and timeouts.

Two lanes:

* **Master lane** — one task at a time, because every one of them runs through
  the single in-process ``master_agent`` and holds its ``_run_lock``. User
  chat, goals, notifications and any cron job without an ``assign_to`` target
  go here.
* **Delegated lane** — a cron job whose ``assign_to`` names a real agent is
  spawned straight into that agent's subprocess and its TASK.MD polled for the
  result. It never touches master's lock, so a long librarian sweep no longer
  blocks the user's next message. Bounded by ``settings.max_concurrent_tasks``.

Usage:
    from app.backend.dispatcher import dispatcher_loop
    asyncio.create_task(dispatcher_loop())
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from loguru import logger

from app.backend.services.graph_events import graph_event_bus
from app.config import settings
from app.utils.db import (
    create_queued_task,
    get_queued_task,
    get_tasks_by_status,
    update_queued_task,
)


async def _deliver_webhook_callback(task_id: str, result: str) -> None:
    """If a completed task has a callback_url in metadata, POST the result."""
    task = get_queued_task(task_id)
    if not task or task.get("source") != "webhook":
        return
    metadata_str = task.get("metadata")
    if not metadata_str:
        return
    try:
        meta = json.loads(metadata_str)
        callback_url = meta.get("callback_url")
        if not callback_url:
            return
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(callback_url, json={
                "task_id": task_id,
                "status": task.get("status", "done"),
                "result": result,
                "structured_result": task.get("structured_result"),
            })
        logger.info(f"Webhook callback delivered for {task_id[:8]}… to {callback_url}")
    except Exception as exc:
        logger.warning(f"Webhook callback failed for {task_id[:8]}…: {exc}")


# Track currently dispatched task IDs to prevent double-dispatch. Covers BOTH
# lanes — it is the double-dispatch guard and the "don't expire this row"
# marker for _check_timeouts.
_running_task_ids: set[str] = set()
_running_tasks: dict[str, asyncio.Task] = {}

# Subset of _running_task_ids currently occupying the master agent. This is the
# slot counter: master runs one task at a time, so anything in here means the
# master lane is closed. Delegated tasks are deliberately absent — they run in
# their own subprocess and must not hold the lane a user's chat needs.
_master_task_ids: set[str] = set()

# How often to re-read a delegated agent's TASK.MD while waiting for it.
_DELEGATED_POLL_INTERVAL = 2.0
# Grace on top of the agent's own task_timeout before the dispatcher gives up
# waiting. The agent enforces its own budget and writes status: error on
# expiry; this only covers the case where it dies without writing anything.
_DELEGATED_TIMEOUT_GRACE = 60
# Upper bound on pending rows examined per loop iteration. Large enough that a
# burst of delegated work can't starve the master lane behind it, small enough
# to stay a cheap query.
_PENDING_WINDOW = 20

# The order pending work is picked up in. A child result is the tail of a
# request already in flight, so it outranks a message the user has only just
# sent; both outrank autonomous work (cron/goal/doctor/webhook).
PENDING_QUERY = (
    "SELECT * FROM task_queue WHERE status='pending' ORDER BY "
    "CASE WHEN source IN ('notification','continuation') THEN 0 "
    "WHEN source IN ('ui','cli','telegram','resume') THEN 1 "
    "ELSE 2 END, created_at, rowid LIMIT ?"
)

# Shutdown signal
_shutdown = asyncio.Event()


def request_shutdown() -> None:
    """Signal the dispatcher to stop."""
    _shutdown.set()


async def stop_running_tasks() -> None:
    """Persist interruption before closing shared services at shutdown."""
    request_shutdown()
    tasks = list(_running_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def cancel_task(task_id: str) -> None:
    row = get_queued_task(task_id)
    if not row or row["status"] not in {"pending", "running", "interrupted"}:
        return
    update_queued_task(task_id, status="cancelled", error="Cancelled by user",
                       completed_at=datetime.now(timezone.utc).isoformat())
    task = _running_tasks.get(task_id)
    if task:
        task.cancel()
    try:
        from app.backend.websocket import ws_manager
        await ws_manager.push_event("task_error", {
            "task_id": task_id, "status": "cancelled", "error": "Cancelled by user",
            "session_id": row.get("session_id"), "source": row.get("source"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Cancellation event delivery failed for {}: {}", task_id, exc)


def _current_metadata(task_id: str, fallback: dict) -> dict:
    """Re-read a task's metadata so a mid-turn write is not clobbered.

    The dispatcher parses metadata once when the task starts, but tools can
    write to the row while the turn is in flight — `_record_abandoned_wait`
    does exactly that. Finalizing from the stale copy would silently drop it.
    """
    row = get_queued_task(task_id)
    if not row:
        return fallback
    try:
        current = json.loads(row.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        return fallback
    return current if isinstance(current, dict) else fallback


async def _execute_task(task_id: str) -> None:
    from app.backend.services.task_runtime import current_task_id
    token = current_task_id.set(task_id)
    try:
        await _execute_task_body(task_id)
    except asyncio.CancelledError:
        row = get_queued_task(task_id)
        if row and row["status"] == "running":
            update_queued_task(task_id, status="interrupted", error="Backend stopped during execution")
        raise
    except Exception as exc:
        row = get_queued_task(task_id)
        if row and row["status"] in {"pending", "running"}:
            update_queued_task(task_id, status="error", error=str(exc), completed_at=datetime.now(timezone.utc).isoformat())
        logger.exception("Task {} execution failed", task_id)
    finally:
        current_task_id.reset(token)
        _running_task_ids.discard(task_id)
        _master_task_ids.discard(task_id)
        _running_tasks.pop(task_id, None)


async def _execute_task_body(task_id: str) -> None:
    """Execute a single task via master_agent and update task_queue."""
    from app.agents.master.agent import master_agent
    from app.backend.websocket import ws_manager
    from app.utils.adapters import Message

    task_row = get_queued_task(task_id)
    if not task_row or task_row["status"] != "pending":
        _running_task_ids.discard(task_id)
        _master_task_ids.discard(task_id)
        return

    prompt = task_row["prompt"]
    source = task_row["source"] or "ui"

    # Parse history from metadata if present
    history: list[Message] | None = None
    # Silent flag — suppress user-facing completion notifications when set
    # (set by _cron_tick in main.py for jobs with `silent: true` or a
    # [SILENT] task tag). Quiet watchdogs should not fire task_complete or
    # morning-report notifications.
    silent = False
    # Cron escalation: if this task is cron-sourced (source=="cron" or the
    # metadata carries a cron_job_id), its success/failure feeds the cron
    # failure-escalation ladder.
    cron_job_id: str | None = None
    meta: dict = {}
    if task_row.get("metadata"):
        try:
            meta = json.loads(task_row["metadata"])
            raw_history = meta.get("history")
            if raw_history:
                history = [Message(role=m["role"], content=m["content"]) for m in raw_history]
            silent = bool(meta.get("silent"))
            cjid = meta.get("cron_job_id")
            if cjid:
                cron_job_id = str(cjid)
        except (json.JSONDecodeError, KeyError):
            silent = False

    # Append user message to history (matches CLI + SSE patterns)
    if history is not None:
        history = history + [Message(role="user", content=prompt)]

    # Task IDs identify executions; they must never become invented chat IDs.
    session_id = task_row.get("session_id") or ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    from app.backend.services.task_runtime import claim_task
    if not claim_task(task_id, session_id, now):
        return
    await ws_manager.push_event("task_update", {
        "task_id": task_id,
        "status": "running",
        "started_at": now,
        "session_id": session_id,
        "source": source,
    })
    # Publish to Redis for MessageBusRelay → WebSocket + agents
    try:
        from app.backend.message_bus import bus as _bus
        await _bus.publish("system:tasks", {
            "type": "task_update",
            "task_id": task_id,
            "status": "running",
            "started_at": now,
            "session_id": session_id,
            "source": source,
        })
    except Exception:
        pass

    # Background work yields the master after a bounded run. Foreground tasks
    # use the agent's own configured timeout and explicit user cancellation.
    _chain_ctx_timeout = (settings.autonomous_run_timeout or None) if source not in {"ui", "cli", "telegram", "resume", "mcp"} else None

    # Emit graph event for task assignment
    await graph_event_bus.emit_task_assigned(
        source="dispatcher",
        target="master",
        task_id=task_id,
    )

    logger.info(
        f"Dispatching task {task_id[:8]}… prompt={prompt} "
        f"(chain_timeout={'unbounded' if _chain_ctx_timeout is None else f'{_chain_ctx_timeout}s'})"
    )

    response_parts: list[str] = []
    # Completed logical messages, split on MessageBoundary.
    message_blocks: list[str] = []
    _msg_start = 0
    # Opening balance for this task's cost. A queue task spans a delegation
    # tree (master + every sub-agent it spawns), so the only way to price it is
    # the delta of total spend across all agents. `task_queue.cost_usd` was
    # 0.0 for all 1175 historical rows because nothing ever wrote it.
    from app.utils.usage_tracker import total_spend_all_agents
    _spend_before = total_spend_all_agents()

    def _task_cost() -> float:
        """Spend attributable to this task, never negative."""
        return max(0.0, total_spend_all_agents() - _spend_before)

    # Telegram streaming: push partial text to the bot as it generates
    telegram_bot = None
    if source == "telegram":
        from app.backend.telegram_bot import get_telegram_bot_instance
        telegram_bot = get_telegram_bot_instance()
        if telegram_bot is None:
            logger.warning(f"Dispatcher: telegram_bot instance is None for task {task_id[:8]}...")
        else:
            logger.info(f"Dispatcher: telegram streaming enabled for task {task_id[:8]}...")

    try:
        async with asyncio.timeout(_chain_ctx_timeout):
            async for event in master_agent.handle_task_stream(
                task=prompt,
                history=history,
                source=source,
                session_id=session_id,
            ):
                from app.backend.routers.tasks import _event_to_dict
                from app.backend.services.task_runtime import append_event
                serialized = _event_to_dict(event)
                if serialized:
                    append_event(task_id, serialized)
                # Collect text deltas for the final result
                from app.utils.adapters import MessageBoundary, TextDelta, UsageStats

                if isinstance(event, MessageBoundary):
                    # End of a logical message. Close the current one so
                    # multi-turn output arrives as SEPARATE messages instead of
                    # one run-on blob ("…builder agent.Builder completed…").
                    _chunk = "".join(response_parts[_msg_start:]).strip()
                    if _chunk:
                        message_blocks.append(_chunk)
                    _msg_start = len(response_parts)
                elif isinstance(event, TextDelta):
                    response_parts.append(event.text)
                    if telegram_bot is not None:
                        telegram_bot.append_streaming_text(task_id, event.text)
                        if len(response_parts) <= 3 or len(response_parts) % 20 == 0:
                            logger.info(
                                f"Dispatcher: streamed {len(event.text)} chars for task {task_id[:8]}... "
                                f"(total deltas={len(response_parts)})")
                    else:
                        if len(response_parts) <= 3:
                            logger.debug(
                                f"Dispatcher: no telegram bot, buffering text for task {task_id[:8]}...")
                elif isinstance(event, UsageStats):
                    # Cost is not carried on UsageStats and cannot be derived
                    # here (the event has no model to price against), and it
                    # would miss sub-agent spend anyway. Priced at finalize
                    # from the all-agent delta instead — see _task_cost().
                    pass

        _tail = "".join(response_parts[_msg_start:]).strip()
        if _tail:
            message_blocks.append(_tail)
        # Blank line between blocks so any consumer that only reads `result`
        # still sees paragraph separation rather than glued sentences.
        result_text = "\n\n".join(message_blocks) if message_blocks else "".join(response_parts)
        # Never substitute the prompt for the result. Echoing the task back at
        # the user reads as "the resume produced nothing useful" even when it
        # succeeded, and the old `len < 25` threshold actively destroyed valid
        # short answers — a correct "RESUME_OK" (9 chars) was replaced by the
        # prompt. If there is genuinely no text, say exactly that.
        if not result_text.strip():
            result_text = (
                "_Task finished with no text output — check the agent trace for what ran._"
            )
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if get_queued_task(task_id)["status"] != "running":
            return
        update_queued_task(
            task_id,
            status="done",
            result=result_text,
            completed_at=completed_at,
            cost_usd=_task_cost(),
            metadata=json.dumps({**_current_metadata(task_id, meta), "messages": message_blocks}),
        )
        if meta.get("notification"):
            from app.backend.services.notification_queue import notification_queue
            try:
                notification_queue.acknowledge([meta["notification"]])
            except Exception as exc:
                # The outbox poller reconciles this persisted success later.
                logger.warning("Notification acknowledgment deferred: {}", exc)
        # Cron escalation: a successful cron-sourced run feeds the
        # failure-escalation ladder — resets failures, clears any disable.
        if cron_job_id:
            try:
                from app.utils.cron_parser import record_cron_success
                record_cron_success(cron_job_id)
            except Exception as exc:
                logger.warning(f"Cron success record failed for {cron_job_id}: {exc}")
        # Suppress user-facing completion notifications for silent jobs.
        # The task is still recorded as done above so last-run tracking and
        # context chaining work; only the external notifications are skipped.
        if not silent:
            await ws_manager.push_event("task_complete", {
                "task_id": task_id,
                "status": "done",
                "result": result_text,
                # Each logical message separately, so the chat can render them
                # as distinct bubbles rather than one concatenated wall.
                "messages": message_blocks,
                "completed_at": completed_at,
                "session_id": session_id,
                "source": source,
                "prompt": prompt,
                "agent": "master",
            })
            try:
                from app.backend.message_bus import bus as _bus2
                await _bus2.publish("system:tasks", {
                    "type": "task_complete",
                    "task_id": task_id,
                    "status": "done",
                    "result": result_text,
                    "messages": message_blocks,
                    "completed_at": completed_at,
                    "session_id": session_id,
                    "source": source,
                    "prompt": prompt,
                    "agent": "master",
                })
            except Exception:
                pass
        logger.info(f"Task {task_id[:8]}… completed ({len(result_text)} chars)")

        # Event-driven indexer: every 20 turns
        from app.utils.db import increment_indexer_counter
        from app.utils.indexer import indexer_tick
        new_count = 0
        try:
            new_count = increment_indexer_counter()
            if new_count % 20 == 0:
                asyncio.create_task(indexer_tick(reason="turn_counter"))
        except Exception:
            pass

        # Auto-trigger memory sweep every 20 turns
        if new_count > 0 and new_count % 20 == 0:
            try:
                import uuid
                sweep_task_id = str(uuid.uuid4())
                create_queued_task(
                    id=sweep_task_id,
                    prompt="memory-sweep",
                    source="system",
                    metadata=json.dumps({"auto_triggered": True, "turn_count": new_count}),
                )
                logger.info(f"Auto-queued memory-sweep task {sweep_task_id[:8]}… at turn {new_count}")
            except Exception as exc:
                logger.warning(f"Failed to auto-queue memory-sweep: {exc}")

        # Morning report — emit on autonomous task completion so an overnight
        # operator sees the result without scraping logs.
        #
        # The primary, reliable trigger is the system:tasks Redis subscriber
        # (app/backend/morning_report_listener.py). This inline hook stays as
        # belt-and-suspenders. Both writes go through asyncio.to_thread so
        # the synchronous I/O inside write_morning_report (file reads + SQLite +
        # git log subprocess) can never starve this fire-and-forget task.
        if (source or "").lower() in ("cron", "goal", "doctor", "webhook") and not silent:
            try:
                from app.backend.morning_report import write_morning_report
                asyncio.create_task(asyncio.to_thread(
                    write_morning_report, "goal_completed", {
                        "task_id": task_id[:8],
                        "source": source or "",
                        "result_preview": result_text[:180] if result_text else "",
                        "via": "dispatcher inline",
                    },
                ))
            except Exception:
                pass

        # Telegram notification on task completion (user preference)
        # Fire only for user-submitted (UI) tasks. Automated/notification-source
        # tasks (resume, notification, etc.) do NOT trigger a Telegram ping —
        # they were not submitted by the user in the UI. Telegram-sourced tasks
        # are already handled by the bot's "Processing..." edit.
        if (source or "").lower() == "ui" and not silent and meta.get("transport") != "sse":
            try:
                from app.backend.telegram_bot import get_telegram_bot_instance

                bot = get_telegram_bot_instance()
                if bot is not None:
                    authorized_chats = bot._auth._authorized_chats | bot._auth._whitelist
                    if authorized_chats:
                        chat_id = next(iter(authorized_chats))
                        reply_to = None
                        if task_row.get("metadata"):
                            try:
                                meta = json.loads(task_row["metadata"])
                                reply_to = meta.get("reply_to_message_id")
                            except Exception:
                                pass
                        # Send header first (with reply_to)
                        header_msg = (
                            f"✅ <b>Task Done</b>\n"
                            f"<i>Source:</i> {source or 'ui'}\n"
                            f"<i>Task:</i> {prompt[:120]}{'...' if len(prompt) > 120 else ''}"
                        )
                        await bot._send_message(chat_id, header_msg, reply_to_message_id=reply_to)
                        # Send full result split into multiple messages (no truncation)
                        from app.backend.telegram_bot import TelegramBot as _TelegramBot
                        result_display = result_text if result_text else "(no text output)"
                        chunks = _TelegramBot._split_text_for_telegram(result_display, max_len=4000)
                        for chunk in chunks:
                            await bot._send_message(chat_id, chunk)
            except Exception:
                pass  # Telegram is best-effort; never fail the task because of it

        # Webhook callback delivery
        await _deliver_webhook_callback(task_id, result_text)

    except TimeoutError as exc:
        if get_queued_task(task_id)["status"] != "running":
            return
        # Two distinct timeout sources land here: the dispatcher's own chain
        # timeout (a bare TimeoutError, message empty) and the agent's internal
        # task_timeout (raised as TimeoutError("Task timed out after Ns")). Use
        # the agent's message when present so foreground tasks aren't mislabeled
        # as "chain timed out after None".
        error_text = str(exc) or f"Task chain timed out after {_chain_ctx_timeout}s"
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(task_id, status="timeout", error=error_text,
                           result="".join(response_parts), completed_at=completed_at, cost_usd=_task_cost())
        await ws_manager.push_event("task_error", {
            "task_id": task_id,
            "status": "timeout",
            "error": error_text,
            "completed_at": completed_at,
            "session_id": session_id,
            "source": source,
            "prompt": prompt,
            "agent": "master",
        })
        try:
            from app.backend.message_bus import bus as _bus3
            await _bus3.publish("system:tasks", {
                "type": "task_error",
                "task_id": task_id,
                "status": "timeout",
                "error": error_text,
                "completed_at": completed_at,
                "session_id": session_id,
                "source": source,
                "prompt": prompt,
                "agent": "master",
            })
        except Exception:
            pass
        # Cron escalation: a timed-out cron-sourced run counts toward the
        # failure-escalation ladder. Notify only on the disable transition.
        if cron_job_id:
            try:
                from app.utils.cron_parser import record_cron_failure, get_failure_count
                if record_cron_failure(cron_job_id):
                    fail_count = get_failure_count(cron_job_id)
                    logger.warning(
                        f"Cron job {cron_job_id} auto-disabled after "
                        f"{fail_count} consecutive failures (timeout)"
                    )
                    await ws_manager.push_event("task_error", {
                        "task_id": task_id,
                        "status": "cron_disabled",
                        "error": (
                            f"Cron job {cron_job_id} auto-disabled after "
                            f"{fail_count} consecutive failures"
                        ),
                        "completed_at": completed_at,
                        "session_id": session_id,
                        "source": source,
                        "prompt": prompt,
                        "agent": "master",
                    })
            except Exception as exc:
                logger.warning(f"Cron failure record failed for {cron_job_id}: {exc}")
        # Telegram notification on task timeout (only for user-submitted UI tasks)
        if (source or "").lower() == "ui" and not silent and meta.get("transport") != "sse":
            try:
                from app.backend.telegram_bot import get_telegram_bot_instance

                bot = get_telegram_bot_instance()
                if bot is not None:
                    authorized_chats = bot._auth._authorized_chats | bot._auth._whitelist
                    if authorized_chats:
                        chat_id = next(iter(authorized_chats))
                        reply_to = None
                        if task_row.get("metadata"):
                            try:
                                meta = json.loads(task_row["metadata"])
                                reply_to = meta.get("reply_to_message_id")
                            except Exception:
                                pass
                        await bot._send_message(
                            chat_id,
                            f"<b>⏰ Task Timeout</b>\n"
                            f"<i>Source:</i> {source or 'ui'}\n"
                            f"<i>Task:</i> {prompt[:120]}{'...' if len(prompt) > 120 else ''}\n\n"
                            f"{error_text}",
                            reply_to_message_id=reply_to,
                        )
            except Exception:
                pass
        logger.warning(f"Task {task_id[:8]}… chain timeout after {_chain_ctx_timeout}s")
        # Webhook callback delivery (timeout status)
        await _deliver_webhook_callback(task_id, error_text)

    except Exception as exc:
        if get_queued_task(task_id)["status"] != "running":
            logger.warning("Post-completion bookkeeping failed for {}: {}", task_id, exc)
            return
        error_text = str(exc)
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(
            task_id,
            status="error",
            error=error_text,
            result="".join(response_parts),
            completed_at=completed_at,
            cost_usd=_task_cost(),
        )
        await ws_manager.push_event("task_error", {
            "task_id": task_id,
            "status": "error",
            "error": error_text,
            "completed_at": completed_at,
            "session_id": session_id,
            "source": source,
            "prompt": prompt,
            "agent": "master",
        })
        try:
            from app.backend.message_bus import bus as _bus4
            await _bus4.publish("system:tasks", {
                "type": "task_error",
                "task_id": task_id,
                "status": "error",
                "error": error_text,
                "completed_at": completed_at,
                "session_id": session_id,
                "source": source,
                "prompt": prompt,
                "agent": "master",
            })
        except Exception:
            pass
        # Cron escalation: a failed cron-sourced run counts toward the
        # failure-escalation ladder. Notify only on the disable transition.
        if cron_job_id:
            try:
                from app.utils.cron_parser import record_cron_failure, get_failure_count
                if record_cron_failure(cron_job_id):
                    fail_count = get_failure_count(cron_job_id)
                    logger.warning(
                        f"Cron job {cron_job_id} auto-disabled after "
                        f"{fail_count} consecutive failures (error)"
                    )
                    await ws_manager.push_event("task_error", {
                        "task_id": task_id,
                        "status": "cron_disabled",
                        "error": (
                            f"Cron job {cron_job_id} auto-disabled after "
                            f"{fail_count} consecutive failures"
                        ),
                        "completed_at": completed_at,
                        "session_id": session_id,
                        "source": source,
                        "prompt": prompt,
                        "agent": "master",
                    })
            except Exception as exc:
                logger.warning(f"Cron failure record failed for {cron_job_id}: {exc}")
        # Telegram notification on task error (only for user-submitted UI tasks)
        if (source or "").lower() == "ui" and not silent and meta.get("transport") != "sse":
            try:
                from app.backend.telegram_bot import get_telegram_bot_instance

                bot = get_telegram_bot_instance()
                if bot is not None:
                    authorized_chats = bot._auth._authorized_chats | bot._auth._whitelist
                    if authorized_chats:
                        chat_id = next(iter(authorized_chats))
                        reply_to = None
                        if task_row.get("metadata"):
                            try:
                                meta = json.loads(task_row["metadata"])
                                reply_to = meta.get("reply_to_message_id")
                            except Exception:
                                pass
                        await bot._send_message(
                            chat_id,
                            f"<b>❌ Task Error</b>\n"
                            f"<i>Source:</i> {source or 'ui'}\n"
                            f"<i>Task:</i> {prompt[:120]}{'...' if len(prompt) > 120 else ''}\n\n"
                            f"{error_text[:300]}",
                            reply_to_message_id=reply_to,
                        )
            except Exception:
                pass
        logger.error(f"Task {task_id[:8]}… failed: {error_text}")
        # Webhook callback delivery (error status)
        await _deliver_webhook_callback(task_id, error_text)

    finally:
        _running_task_ids.discard(task_id)


def direct_target(task_row: dict) -> str | None:
    """Agent that should run this task directly, or None for the master lane.

    Only cron rows are eligible: `assign_to` is written by the cron tick and
    the cron router, and nothing else produces it. A target naming master, or
    naming a directory that does not exist, falls back to the master lane
    rather than failing the job.
    """
    if (task_row.get("source") or "").lower() != "cron":
        return None
    try:
        meta = json.loads(task_row.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    target = str(meta.get("assign_to") or "").strip()
    if not target or target == "master":
        return None
    if not (settings.agents_dir / target).is_dir():
        logger.warning(
            "Cron task {}… targets unknown agent '{}' — routing through master",
            task_row.get("id", "")[:8], target,
        )
        return None
    return target


def _agent_task_timeout(agent_name: str) -> int:
    """The agent's own task budget, resolved the way BaseAgent resolves it:
    agent-settings.json → CONFIG.yaml runner block → settings default.

    Returns 0 for "unbounded", matching BaseAgent's convention.
    """
    try:
        from app.utils.agent_settings import resolve_runner_settings
        value = resolve_runner_settings(agent_name).get("task_timeout")
    except Exception:
        value = None
    if value is None:
        try:
            from app.agents.base.context import _parse_runner_config
            cfg = (settings.agents_dir / agent_name / "CONFIG.yaml").read_text(encoding="utf-8")
            value = _parse_runner_config(cfg).get("task_timeout")
        except Exception:
            value = None
    if value is None:
        value = settings.task_timeout
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return settings.task_timeout


async def _push_task_state(event: str, payload: dict) -> None:
    """Emit a task lifecycle event on both the WebSocket and the Redis bus.

    Each leg is independently best-effort: a dead Redis must not cost the UI
    its update, and vice versa.
    """
    try:
        from app.backend.websocket import ws_manager
        await ws_manager.push_event(event, payload)
    except Exception as exc:
        logger.warning("WS {} delivery failed for {}: {}", event, payload.get("task_id"), exc)
    try:
        from app.backend.message_bus import bus
        await bus.publish("system:tasks", {"type": event, **payload})
    except Exception:
        pass


async def _execute_delegated_task(task_id: str, agent_name: str) -> None:
    """Delegated-lane wrapper — mirrors _execute_task's bookkeeping."""
    from app.backend.services.task_runtime import current_task_id

    token = current_task_id.set(task_id)
    try:
        await _execute_delegated_task_body(task_id, agent_name)
    except asyncio.CancelledError:
        row = get_queued_task(task_id)
        if row and row["status"] == "running":
            update_queued_task(task_id, status="interrupted",
                               error="Backend stopped during execution")
        raise
    except Exception as exc:
        row = get_queued_task(task_id)
        if row and row["status"] in {"pending", "running"}:
            update_queued_task(task_id, status="error", error=str(exc),
                               completed_at=datetime.now(timezone.utc).isoformat())
        logger.exception("Delegated task {} execution failed", task_id)
    finally:
        current_task_id.reset(token)
        _running_task_ids.discard(task_id)
        _running_tasks.pop(task_id, None)


async def _execute_delegated_task_body(task_id: str, agent_name: str) -> None:
    """Run a cron task directly on its target agent, bypassing master.

    Spawns the agent's subprocess with the task, then polls its TASK.MD until
    it reaches a terminal status. Master is never involved: it holds no lock,
    burns no turn re-deriving the routing, and — because TASK.MD records
    `assigned_by: dispatcher` — gets no completion notification to summarize
    afterwards. The result lands in task_queue (and the morning report) where
    an operator can read it.
    """
    from app.backend.services.notification_queue import DISPATCHER_PARENT
    from app.backend.services.task_runtime import claim_task
    from app.utils.frontmatter import parse_frontmatter_fields
    from app.utils.tools.delegation import (
        SpawnAgentTool,
        _poll_one_dag,
        _resolve_checkpoint,
        _spawn_response_indicates_failure,
        _task_path,
    )
    from app.utils.usage_tracker import total_spend_all_agents

    task_row = get_queued_task(task_id)
    if not task_row or task_row["status"] != "pending":
        _running_task_ids.discard(task_id)
        return

    prompt = task_row["prompt"]
    source = task_row["source"] or "cron"
    session_id = task_row.get("session_id") or ""
    try:
        meta = json.loads(task_row.get("metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    silent = bool(meta.get("silent"))
    cron_job_id = str(meta["cron_job_id"]) if meta.get("cron_job_id") else None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not claim_task(task_id, session_id, now, agent=agent_name):
        return

    _spend_before = total_spend_all_agents()

    def _task_cost() -> float:
        return max(0.0, total_spend_all_agents() - _spend_before)

    await _push_task_state("task_update", {
        "task_id": task_id, "status": "running", "started_at": now,
        "session_id": session_id, "source": source, "agent": agent_name,
    })
    await graph_event_bus.emit_task_assigned(
        source="dispatcher", target=agent_name, task_id=task_id,
    )

    budget = _agent_task_timeout(agent_name)
    logger.info(
        "Dispatching task {}… directly to '{}' (budget={})",
        task_id[:8], agent_name,
        "unbounded" if budget <= 0 else f"{budget}s",
    )

    spawn_msg = await SpawnAgentTool(
        session_id=session_id or None, caller=DISPATCHER_PARENT,
    ).execute(agent_name=agent_name, task=prompt)

    if _spawn_response_indicates_failure(spawn_msg):
        await _finalize_delegated(
            task_id, agent_name, "error", "", f"Spawn refused: {spawn_msg}",
            source=source, prompt=prompt, session_id=session_id,
            silent=silent, cron_job_id=cron_job_id, cost=_task_cost(),
        )
        return

    # Pin the run we just started. A concurrent spawn into the same agent
    # would rewrite TASK.MD, and polling it blindly would report that other
    # run's outcome as ours.
    task_path = _task_path(agent_name)
    try:
        run_task_id = parse_frontmatter_fields(
            task_path.read_text(encoding="utf-8")
        ).get("task_id", "")
    except OSError:
        run_task_id = ""

    deadline = None if budget <= 0 else time.monotonic() + budget + _DELEGATED_TIMEOUT_GRACE
    status, result, error = "pending", "", ""
    while deadline is None or time.monotonic() < deadline:
        await asyncio.sleep(_DELEGATED_POLL_INTERVAL)
        if _shutdown.is_set():
            row = get_queued_task(task_id)
            if row and row["status"] == "running":
                update_queued_task(task_id, status="interrupted",
                                   error="Backend stopped during execution")
            return
        status, result, error = await _poll_one_dag(agent_name)
        # Re-read the identity from the same observation that produced the
        # status, not before it: a reassignment landing between the two reads
        # would otherwise hand us the other run's result as our own. The
        # runner strips task_id once it finishes, so an absent id is ours —
        # only a DIFFERENT one means we are looking at someone else's run.
        try:
            current = parse_frontmatter_fields(
                task_path.read_text(encoding="utf-8")
            ).get("task_id", "")
        except OSError:
            current = run_task_id
        if run_task_id and current and current != run_task_id:
            status, result, error = "error", "", (
                f"Superseded — '{agent_name}' was reassigned to task "
                f"{current[:8]}… before this run finished"
            )
            break
        if status in ("done", "error"):
            break
    else:
        status, error = "timeout", (
            f"Agent '{agent_name}' did not finish within {budget}s "
            f"(+{_DELEGATED_TIMEOUT_GRACE}s dispatcher grace)"
        )

    # Commit or roll back the pre-spawn git checkpoint. On the master lane
    # wait_for_agent does this; nothing else would here.
    try:
        banner = await _resolve_checkpoint(agent_name, status, prompt[:120])
        if banner and result:
            result = banner + result
    except Exception as exc:
        logger.warning("Checkpoint resolution failed for {}: {}", agent_name, exc)

    await _finalize_delegated(
        task_id, agent_name, status, result, error,
        source=source, prompt=prompt, session_id=session_id,
        silent=silent, cron_job_id=cron_job_id, cost=_task_cost(),
    )


async def _finalize_delegated(
    task_id: str,
    agent_name: str,
    status: str,
    result: str,
    error: str,
    *,
    source: str,
    prompt: str,
    session_id: str,
    silent: bool,
    cron_job_id: str | None,
    cost: float,
) -> None:
    """Write a delegated run's outcome to task_queue and announce it."""
    row = get_queued_task(task_id)
    if not row or row["status"] != "running":
        return  # cancelled or already finalized elsewhere

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if status == "done":
        if not result.strip():
            result = (
                "_Task finished with no text output — check the agent trace for what ran._"
            )
        update_queued_task(task_id, status="done", result=result,
                           completed_at=completed_at, cost_usd=cost)
    else:
        update_queued_task(task_id, status=status, error=error, result=result,
                           completed_at=completed_at, cost_usd=cost)

    # Cron escalation ladder — same accounting the master lane does.
    if cron_job_id:
        try:
            if status == "done":
                from app.utils.cron_parser import record_cron_success
                record_cron_success(cron_job_id)
            else:
                from app.utils.cron_parser import get_failure_count, record_cron_failure
                if record_cron_failure(cron_job_id):
                    logger.warning(
                        "Cron job {} auto-disabled after {} consecutive failures",
                        cron_job_id, get_failure_count(cron_job_id),
                    )
                    await _push_task_state("task_error", {
                        "task_id": task_id, "status": "cron_disabled",
                        "error": f"Cron job {cron_job_id} auto-disabled after "
                                 f"{get_failure_count(cron_job_id)} consecutive failures",
                        "session_id": session_id, "source": source,
                    })
        except Exception as exc:
            logger.warning("Cron escalation record failed for {}: {}", cron_job_id, exc)

    if not silent:
        payload = {
            "task_id": task_id, "status": status, "completed_at": completed_at,
            "session_id": session_id, "source": source, "prompt": prompt,
            "agent": agent_name,
        }
        if status == "done":
            await _push_task_state("task_complete", {
                **payload, "result": result, "messages": [result],
            })
        else:
            await _push_task_state("task_error", {**payload, "error": error})

    if status == "done":
        logger.info(
            "Delegated task {}… completed on '{}' ({} chars)",
            task_id[:8], agent_name, len(result),
        )
    else:
        logger.error(
            "Delegated task {}… {} on '{}': {}", task_id[:8], status, agent_name, error,
        )

    # Morning report — with master out of the loop there is no chat message
    # narrating this run, so the report is the operator's view of it.
    if not silent:
        try:
            from app.backend.morning_report import write_morning_report
            asyncio.create_task(asyncio.to_thread(
                write_morning_report, "goal_completed", {
                    "task_id": task_id[:8],
                    "source": source,
                    "agent": agent_name,
                    "result_preview": (result or error)[:180],
                    "via": "dispatcher direct route",
                },
            ))
        except Exception:
            pass

    await _deliver_webhook_callback(task_id, result or error)


async def _check_timeouts() -> None:
    """Expire orphaned rows; live executions own their configured timeout."""
    running = get_tasks_by_status("running")
    now = datetime.now(timezone.utc)
    timeout_seconds = settings.task_timeout
    if timeout_seconds <= 0:
        return

    for task in running:
        # Removing a live ID doesn't cancel its coroutine. It only frees a
        # fictitious slot, and that coroutine can later overwrite timeout with
        # done. BaseAgent enforces its per-agent timeout (master may use 0).
        if task["id"] in _running_task_ids:
            continue
        started = task.get("started_at")
        if not started:
            continue
        try:
            started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            elapsed = (now - started_dt).total_seconds()
            if elapsed > timeout_seconds:
                tid = task["id"]
                update_queued_task(tid, status="timeout", error=f"Timed out after {elapsed:.0f}s")
                _running_task_ids.discard(tid)
                logger.warning(f"Task {tid[:8]}… timed out after {elapsed:.0f}s")
                try:
                    from app.backend.websocket import ws_manager
                    await ws_manager.push_event("task_error", {
                        "task_id": tid,
                        "status": "timeout",
                        "error": f"Timed out after {elapsed:.0f}s",
                        "session_id": task.get("session_id"),
                        "source": task.get("source"),
                    })
                except Exception:
                    pass
        except (ValueError, TypeError):
            continue


async def dispatcher_loop() -> None:
    """Main dispatcher loop. Poll task_queue every 1s, dispatch pending tasks."""
    logger.info("Task dispatcher started")
    _shutdown.clear()

    while not _shutdown.is_set():
        try:
            # Check for timed-out tasks
            await _check_timeouts()

            # How many slots are available in each lane?
            # Master runs one task at a time — everything on that lane shares
            # the one in-process agent and its _run_lock. Do not mark lock
            # waiters running or let them occupy the slot.
            from app.agents.master.agent import master_agent
            master_free = not master_agent.is_busy() and not _master_task_ids
            delegated_running = len(_running_task_ids) - len(_master_task_ids)
            delegated_free = max(0, settings.max_concurrent_tasks - delegated_running)
            if not master_free and delegated_free <= 0:
                await asyncio.sleep(0.5)
                continue

            # Fetch a window of pending tasks and assign each to its lane.
            # Reading more rows than either lane can take is deliberate: a
            # queued cron sweep must not hide the user's chat message behind
            # it just because the delegated lane happens to be full.
            from app.utils.db import get_db
            pending = [dict(r) for r in get_db().execute(
                PENDING_QUERY, (_PENDING_WINDOW,)
            ).fetchall()]
            for task in pending:
                tid = task["id"]
                if tid in _running_task_ids:
                    continue  # already dispatched
                target = direct_target(task)
                if target is None and not master_free:
                    continue
                if target is not None and delegated_free <= 0:
                    continue
                # Check autonomous budget for non-user tasks
                source = task.get("source", "ui")
                if source in ("cron", "goal", "doctor", "webhook"):
                    from app.utils.cost_governor import is_autonomous_budget_exhausted
                    if is_autonomous_budget_exhausted():
                        logger.info(f"Skipping autonomous task {tid[:8]}… (daily budget exhausted)")
                        continue
                # Event-driven indexer: new session detection
                session_id = task.get("session_id")
                if session_id:
                    from app.utils.db import is_new_session
                    from app.utils.indexer import indexer_tick
                    try:
                        if is_new_session(session_id):
                            asyncio.create_task(indexer_tick(reason="new_session"))
                    except Exception:
                        pass

                _running_task_ids.add(tid)
                if target is None:
                    master_free = False
                    _master_task_ids.add(tid)
                    _running_tasks[tid] = asyncio.create_task(_execute_task(tid))
                else:
                    delegated_free -= 1
                    _running_tasks[tid] = asyncio.create_task(
                        _execute_delegated_task(tid, target)
                    )

            # Goal-driven task creation: when no pending or running tasks, check GOALS.MD
            if not pending and not _running_task_ids:
                await _check_goals()

        except Exception as exc:
            logger.error(f"Dispatcher error: {exc}")

        await asyncio.sleep(1)

    logger.info("Task dispatcher stopped")


_last_goal_check: float = 0.0  # throttle goal checks to every 60s


async def _check_goals() -> None:
    """If master has active goals and no tasks running, create a goal task."""
    import time

    global _last_goal_check
    now = time.monotonic()
    if now - _last_goal_check < 60:
        return
    _last_goal_check = now

    from app.utils.cost_governor import is_autonomous_budget_exhausted
    if is_autonomous_budget_exhausted():
        return

    goals_path = settings.agents_dir / "master" / "GOALS.MD"
    if not goals_path.exists():
        return

    text = goals_path.read_text(encoding="utf-8")
    # Find first unchecked active goal
    import re
    active_match = re.search(r"## Active\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not active_match:
        return

    active_text = active_match.group(1).strip()
    unchecked = re.findall(r"- \[ \] (.+)", active_text)
    if not unchecked:
        return

    top_goal = unchecked[0].strip()

    # Duplicate guard: if a pending/running task already represents this goal
    # (e.g. resumed from a prior backend crash), don't dispatch a second one.
    # The dispatcher will pick the existing pending task on its next iteration.
    from app.utils.db import get_tasks_by_status
    goal_prompt = f"[Goal] {top_goal}"
    for status in ("pending", "running"):
        for t in get_tasks_by_status(status) or []:
            if (t.get("source") or "").lower() == "goal" and (t.get("prompt") or "") == goal_prompt:
                logger.debug(
                    "Goal-driven dispatch: skipped — task already {} ({})",
                    status, t["id"][:8],
                )
                return

    logger.info(f"Goal-driven dispatch: '{top_goal}'")

    import uuid
    task_id = str(uuid.uuid4())
    create_queued_task(
        id=task_id,
        prompt=goal_prompt,
        source="goal",
    )
