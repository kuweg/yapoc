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

from app.config import settings
from app.utils.db import (
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
                "result": result[:5000],
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
    if task_row.get("metadata"):
        try:
            meta = json.loads(task_row["metadata"])
            raw_history = meta.get("history")
            if raw_history:
                history = [Message(role=m["role"], content=m["content"]) for m in raw_history]
        except (json.JSONDecodeError, KeyError):
            pass

    # Append user message to history (matches CLI + SSE patterns)
    if history is not None:
        history = history + [Message(role="user", content=prompt)]

    # Set session_id on master so events get emitted for real-time streaming
    session_id = task_row.get("session_id") or task_id
    master_agent._session_id = session_id

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    update_queued_task(task_id, status="running", started_at=now, assigned_agent="master",
                       session_id=session_id)
    await ws_manager.push_event("task_update", {
        "task_id": task_id,
        "status": "running",
        "started_at": now,
    })

    # Total chain timeout: prevents infinite delegation chains.
    # 2x master's task_timeout gives sub-agents time to finish.
    _chain_timeout = settings.task_timeout * 2

    logger.info(f"Dispatching task {task_id[:8]}… prompt={prompt[:80]} (chain_timeout={_chain_timeout}s)")

    response_parts: list[str] = []
    total_cost = 0.0
    try:
        async with asyncio.timeout(_chain_timeout):
            async for event in master_agent.handle_task_stream(
                task=prompt,
                history=history,
                source=source,
            ):
                # Collect text deltas for the final result
                from app.utils.adapters import TextDelta, UsageStats

                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
                elif isinstance(event, UsageStats):
                    # Accumulate cost if available
                    pass

        result_text = "".join(response_parts)
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(
            task_id,
            status="done",
            result=result_text[:10000],
            completed_at=completed_at,
        )
        await ws_manager.push_event("task_complete", {
            "task_id": task_id,
            "status": "done",
            "result": result_text[:2000],
            "completed_at": completed_at,
        })
        logger.info(f"Task {task_id[:8]}… completed ({len(result_text)} chars)")

        # Webhook callback delivery
        await _deliver_webhook_callback(task_id, result_text)

    except TimeoutError:
        error_text = f"Task chain timed out after {_chain_timeout}s"
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(task_id, status="timeout", error=error_text, completed_at=completed_at)
        await ws_manager.push_event("task_error", {
            "task_id": task_id, "status": "timeout", "error": error_text, "completed_at": completed_at,
        })
        # Return partial result if any text was collected
        partial = "".join(response_parts)
        if partial:
            update_queued_task(task_id, result=f"[PARTIAL] {partial[:5000]}")
        logger.warning(f"Task {task_id[:8]}… chain timeout after {_chain_timeout}s")

    except Exception as exc:
        error_text = str(exc)
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_queued_task(
            task_id,
            status="error",
            error=error_text[:5000],
            completed_at=completed_at,
        )
        await ws_manager.push_event("task_error", {
            "task_id": task_id,
            "status": "error",
            "error": error_text[:2000],
            "completed_at": completed_at,
        })
        logger.error(f"Task {task_id[:8]}… failed: {error_text[:200]}")

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
    logger.info(f"Goal-driven dispatch: '{top_goal[:80]}'")

    import uuid
    task_id = str(uuid.uuid4())
    create_queued_task(
        id=task_id,
        prompt=f"[Goal] {top_goal}",
        source="goal",
    )
