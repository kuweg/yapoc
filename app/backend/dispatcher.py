"""Task Dispatcher — background loop that polls task_queue and executes tasks.

Started as an asyncio task in main.py lifespan. Picks up pending tasks from
the SQLite task_queue, dispatches them to the master agent, and writes results
back. Handles concurrency limits and timeouts.

Usage:
    from app.backend.dispatcher import dispatcher_loop
    asyncio.create_task(dispatcher_loop())
"""

from __future__ import annotations

import asyncio
import json
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
            })
        logger.info(f"Webhook callback delivered for {task_id[:8]}… to {callback_url}")
    except Exception as exc:
        logger.warning(f"Webhook callback failed for {task_id[:8]}…: {exc}")


# Track currently dispatched task IDs to prevent double-dispatch
_running_task_ids: set[str] = set()

# Shutdown signal
_shutdown = asyncio.Event()


def request_shutdown() -> None:
    """Signal the dispatcher to stop."""
    _shutdown.set()


async def _execute_task(task_id: str) -> None:
    """Execute a single task via master_agent and update task_queue."""
    from app.agents.master.agent import master_agent
    from app.backend.websocket import ws_manager
    from app.utils.adapters import Message

    task_row = get_queued_task(task_id)
    if not task_row:
        _running_task_ids.discard(task_id)
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

    session_id = task_row.get("session_id") or task_id

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    update_queued_task(task_id, status="running", started_at=now, assigned_agent="master",
                       session_id=session_id)
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

    # Total chain timeout: prevents infinite delegation chains.
    # 2x master's task_timeout gives sub-agents time to finish.
    # Fix 2.2: master is autonomous — bypass the chain timeout entirely so
    # long-running orchestration is not cancelled at the parent level. Cost
    # protection lives in budget_per_agent_usd / budget_per_task_usd; sub-
    # agents keep their own task_timeout. Non-master targets (rare here, all
    # tasks route through master) retain the original guard.
    if settings.task_timeout > 0:
        _chain_timeout: int | None = settings.task_timeout * 2
    else:
        _chain_timeout = None
    _chain_ctx_timeout: int | None = None if _chain_timeout is None else _chain_timeout
    # Master is unbounded — see Fix 2.2.
    _chain_ctx_timeout = None  # all tasks dispatched here go through master

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
    total_cost = 0.0

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
                # Collect text deltas for the final result
                from app.utils.adapters import TextDelta, UsageStats

                if isinstance(event, TextDelta):
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
                    # Accumulate cost if available
                    pass

        result_text = "".join(response_parts)
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
        update_queued_task(
            task_id,
            status="done",
            result=result_text,
            completed_at=completed_at,
        )
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
        if new_count % 20 == 0:
            try:
                sweep_task_id = create_queued_task(
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
        if (source or "").lower() == "ui" and not silent:
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

    except TimeoutError:
        error_text = f"Task chain timed out after {_chain_timeout}s"
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(task_id, status="timeout", error=error_text, completed_at=completed_at)
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
        # Return partial result if any text was collected
        partial = "".join(response_parts)
        if partial:
            update_queued_task(task_id, result=f"[PARTIAL] {partial}")
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
        if (source or "").lower() == "ui":
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
        logger.warning(f"Task {task_id[:8]}… chain timeout after {_chain_timeout}s")

    except Exception as exc:
        error_text = str(exc)
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(
            task_id,
            status="error",
            error=error_text,
            completed_at=completed_at,
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
        if (source or "").lower() == "ui":
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

    finally:
        _running_task_ids.discard(task_id)


async def _check_timeouts() -> None:
    """Mark stale running tasks as timed out."""
    running = get_tasks_by_status("running")
    now = datetime.now(timezone.utc)
    timeout_seconds = settings.task_timeout

    for task in running:
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
                    })
                except Exception:
                    pass
        except (ValueError, TypeError):
            continue


async def dispatcher_loop() -> None:
    """Main dispatcher loop. Poll task_queue every 1s, dispatch pending tasks."""
    logger.info("Task dispatcher started")

    while not _shutdown.is_set():
        try:
            # Check for timed-out tasks
            await _check_timeouts()

            # How many slots are available?
            running_count = len(_running_task_ids)
            available = settings.max_concurrent_tasks - running_count
            if available <= 0:
                await asyncio.sleep(1)
                continue

            # Fetch pending tasks
            pending = get_tasks_by_status("pending", limit=available)
            for task in pending:
                tid = task["id"]
                if tid in _running_task_ids:
                    continue  # already dispatched
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
                asyncio.create_task(_execute_task(tid))

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
