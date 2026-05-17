"""Morning Report Redis subscriber — reliable trigger for autonomous task completion.

Why this exists: the inline `write_morning_report` hooks on
``dispatcher._execute_task`` and ``master.handle_task_stream``'s finally
silently miss for some cron-source tasks. The dispatcher's
``bus.publish("system:tasks", {"type": "task_complete", ...})`` does
fire reliably (we have ``BusRelay: system_tasks task_complete → WS``
log evidence on every completion), so subscribing to that channel is
the most decoupled, reliable trigger.

Diagnosed root cause: ``write_morning_report`` performs synchronous I/O
(file reads + SQLite query + ``subprocess.run`` for git log). When
invoked from inside the dispatcher's fire-and-forget asyncio task,
this can starve the event loop long enough that the post-publish
``logger.info`` and the inline hook get pre-empted before reaching
disk. The subscriber here always defers to ``asyncio.to_thread`` so
the event loop stays unblocked regardless of how slow the write is.

Pattern mirrors ``app/backend/relay.py`` MessageBusRelay loops:
reconnect-on-error with a short sleep.
"""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.backend.morning_report import write_morning_report


_AUTONOMOUS_SOURCES = frozenset({"cron", "goal", "doctor", "webhook"})


async def morning_report_subscriber(shutdown_event: asyncio.Event | None = None) -> None:
    """Subscribe to ``system:tasks`` and trigger ``write_morning_report``
    on every ``task_complete`` with an autonomous source.

    Runs as a background task started from the FastAPI lifespan. The
    inline hooks in dispatcher/master are kept as belt-and-suspenders;
    this subscriber is the primary, reliable trigger.

    The write itself is deferred to ``asyncio.to_thread`` so the
    subscriber's pubsub loop is never blocked by file/SQLite/git I/O.
    """
    from app.backend.message_bus import bus

    def _is_shutdown() -> bool:
        return bool(shutdown_event and shutdown_event.is_set())

    logger.info("morning_report subscriber: starting (channel=system:tasks)")
    while not _is_shutdown():
        try:
            async for msg in bus.subscribe("system:tasks"):
                if _is_shutdown():
                    break
                data: Any = msg.get("data") if isinstance(msg, dict) else None
                if not isinstance(data, dict):
                    continue
                if data.get("type") != "task_complete":
                    continue
                src = (data.get("source") or "").lower()
                if src not in _AUTONOMOUS_SOURCES:
                    continue
                task_id = str(data.get("task_id", ""))
                payload = {
                    "task_id": task_id[:8] if task_id else "",
                    "source": src,
                    "result_preview": str(data.get("result", ""))[:180],
                    "via": "system:tasks subscriber",
                }
                # Fire-and-forget thread-pool write so the subscriber's
                # next event isn't delayed by file I/O or git subprocess.
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            write_morning_report, "goal_completed", payload,
                        )
                    )
                    logger.bind(task_id=payload["task_id"], source=src).info(
                        "morning_report subscriber: scheduled write for {} ({})",
                        payload["task_id"], src,
                    )
                except RuntimeError as exc:
                    # asyncio.create_task can raise if the loop is closing
                    logger.warning(
                        "morning_report subscriber: create_task failed ({}); skipping",
                        exc,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_shutdown():
                break
            logger.warning(
                "morning_report subscriber: pubsub error (reconnecting in 2s): {}",
                exc,
            )
            await asyncio.sleep(2)

    logger.info("morning_report subscriber: stopped")
