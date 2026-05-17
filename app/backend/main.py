import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from loguru import logger
from fastapi.middleware.cors import CORSMiddleware

from app.backend.routers import agents_router, costs_router, files_router, health_router, memory_graph_router, metrics_router, models_router, notification_trace_router, sessions_router, stale_tasks_router, tasks_router, test_endpoint_router, vault_router, voice_router, webhook_router
from app.backend.websocket import websocket_endpoint
from app.backend.message_bus import bus
from app.config import settings


def _pid_alive_local(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cleanup_stale_agent_statuses() -> None:
    """On server start, mark dead sub-agents as terminated and clear stale TASK.MD files."""
    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("base", "master", "shared"):
            continue
        status_path = agent_dir / "STATUS.json"
        if not status_path.exists():
            # No STATUS.json but TASK.MD may be stale — clear it
            task_path = agent_dir / "TASK.MD"
            if task_path.exists():
                content = task_path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"^status:\s*(pending|running)", content, re.MULTILINE):
                    task_path.write_text("")
            continue
        try:
            status = json.loads(status_path.read_text())
            state = status.get("state", "")
            pid = status.get("pid")
            if state in ("idle", "running", "spawning"):
                alive = bool(pid and _pid_alive_local(pid))
                if not alive:
                    status["state"] = "terminated"
                    status["task_summary"] = "shutdown: server restart"
                    status_path.write_text(json.dumps(status, indent=2))
                    # Clear stale TASK.MD so sidebar doesn't show "busy"
                    task_path = agent_dir / "TASK.MD"
                    if task_path.exists():
                        content = task_path.read_text(encoding="utf-8", errors="ignore")
                        if re.search(r"^status:\s*(pending|running)", content, re.MULTILINE):
                            task_path.write_text("")
        except Exception:
            pass


async def _doctor_tick() -> None:
    """Run a single Doctor health check (called by APScheduler)."""
    from app.agents.doctor.agent import doctor_agent

    try:
        await doctor_agent.run_health_check()
    except Exception:
        pass  # Doctor logs its own errors


async def _model_manager_tick() -> None:
    """Run a Model Manager audit (called by APScheduler)."""
    from app.agents.model_manager.agent import model_manager_agent

    try:
        await model_manager_agent.run_model_audit()
    except Exception:
        pass  # Model Manager logs its own errors


async def _indexer_tick() -> None:
    """Run the memory indexer (called by APScheduler)."""
    import asyncio
    from app.utils.indexer import run_indexer

    try:
        await asyncio.to_thread(run_indexer)
    except Exception:
        pass  # indexer logs its own errors


async def _master_notification_watcher() -> None:
    """Background task: watch master's TASK.MD for notification triggers written by
    notify_parent tool and auto-invoke master_agent to process the queue.

    Sub-agents call notify_parent("master") which enqueues a Notification and writes
    a trigger TASK.MD (status: pending). Master has no AgentRunner, so this watcher
    fills that role for notification-triggered tasks only.
    """
    from app.agents.master.agent import master_agent
    from app.backend.services.notification_queue import notification_queue

    task_path = settings.agents_dir / "master" / "TASK.MD"
    status_path = settings.agents_dir / "master" / "STATUS.json"

    while True:
        await asyncio.sleep(3)
        try:
            if not task_path.exists():
                continue
            content = task_path.read_text(encoding="utf-8")
            # Only handle notification-triggered tasks (assigned_by preserved from chain)
            if not re.search(r"^status:\s*pending", content, re.MULTILINE):
                continue
            # Check it was written by notify_parent (not a user-sent task)
            trigger_body = re.search(r"\[Process incoming notifications from sub-agents\]", content)
            if not trigger_body:
                continue  # user task — leave it alone
            trigger_session_match = re.search(r"^session_id:\s*(.*)$", content, re.MULTILINE)
            trigger_session_id = trigger_session_match.group(1).strip() if trigger_session_match else ""
            # Guard: don't interrupt a running master.
            # Authoritative concurrency check via _run_lock state; STATUS.json
            # is a UI denormalization and not safe for routing. See Fix 1.3.
            if master_agent.is_busy():
                continue
            # Only fire if there are actual pending notifications
            if notification_queue.pending_count("master") == 0:
                # No pending notifications; if a stale trigger exists, clear it
                try:
                    content = task_path.read_text(encoding="utf-8")
                    if re.search(r"\[Process incoming.*notifications", content):
                        task_path.write_text("")
                except OSError:
                    pass
                continue

            # Process notifications session-by-session so results stay scoped
            # to the originating UI chat.
            session_ids = notification_queue.pending_sessions("master")
            if not session_ids:
                session_ids = [""]

            if trigger_session_id and trigger_session_id in session_ids:
                session_ids = [trigger_session_id] + [sid for sid in session_ids if sid != trigger_session_id]

            logger.info(
                "Notification watcher: firing master for sessions={} trigger_sid={!r}",
                [sid[:8] if sid else "<empty>" for sid in session_ids],
                trigger_session_id[:8] if trigger_session_id else "<empty>",
            )

            # Don't consume the trigger before processing — if master fails,
            # the trigger should remain for retry. Mark consumed only after
            # all sessions are processed successfully.
            for sid in session_ids:
                if notification_queue.pending_count("master", session_id=sid) == 0:
                    continue

                async for _ in master_agent.handle_task_stream(
                    task=(
                        "[Auto-notification] Sub-agent task(s) just completed. "
                        "Read the sub-agent results via read_task_result if needed, "
                        "then write ONE short summary message for the user describing "
                        "what was accomplished. Do NOT spawn agents, do NOT restart servers, "
                        "do NOT re-verify. Your only job: surface the outcome to the user."
                    ),
                    source="notification",
                    session_id=sid,
                ):
                    pass  # events consumed; result written to RESULT.MD by BaseAgent

                # Drain notification_queue so this session doesn't re-trigger
                notification_queue.drain("master", session_id=sid)

                # Push result to WebSocket: session_event for chat panel AND
                # task_complete for downstream subscribers.
                try:
                    from app.backend.websocket import ws_manager

                    result_text = (settings.agents_dir / "master" / "RESULT.MD").read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).strip()
                    if result_text:
                        if sid:
                            await ws_manager.push_session_event(
                                sid,
                                {"type": "notification_result", "text": result_text},
                            )
                            await ws_manager.push_event(
                                "task_complete",
                                {
                                    "session_id": sid,
                                    "text": result_text,
                                    "source": "notification",
                                    "agent": "master",
                                },
                            )
                            logger.info(
                                "Notification watcher: pushed master result to session={} ({} chars)",
                                sid[:8],
                                len(result_text),
                            )
                        else:
                            await ws_manager.push_event(
                                "notification_result",
                                {"text": result_text, "session_id": ""},
                            )
                            logger.info(
                                "Notification watcher: broadcast master result (no session, {} chars)",
                                len(result_text),
                            )
                    else:
                        logger.warning(
                            "Notification watcher: RESULT.MD empty after master run for session={}",
                            (sid or "<empty>")[:8],
                        )
                except Exception as _push_exc:
                    logger.warning(
                        "Notification watcher: event push failed for {}: {}",
                        sid,
                        _push_exc,
                    )

            # After processing all sessions, clear any remaining trigger
            # (handle_task_stream normally clears via set_task + run_stream_with_tools,
            # but clean up if a stale trigger persists).
            try:
                content = task_path.read_text(encoding="utf-8")
                if re.search(r"\[Process incoming.*notifications", content):
                    task_path.write_text("")
            except OSError:
                pass
        except Exception as _watcher_exc:
            logger.warning(
                "Notification watcher iteration failed (will retry): {}",
                _watcher_exc,
            )


async def _master_redis_watcher() -> None:
    """Background task: read master's Redis inbox for child-agent results.

    Child agents publish ``task_result`` to ``agent:master:inbox`` on
    completion. Master has no AgentRunner, so this watcher fills that role
    for Redis-delivered notifications.

    Drains notification_queue after each session to prevent re-triggers.
    """
    from app.agents.master.agent import master_agent
    from app.backend.message_bus import bus as _bus
    from app.backend.websocket import ws_manager
    from app.backend.services.notification_queue import notification_queue

    inbox = "agent:master:inbox"
    group = "master_group"
    consumer = f"master_{os.getpid()}"
    status_path = settings.agents_dir / "master" / "STATUS.json"

    # Create consumer group (idempotent)
    await _bus.stream_create_group(inbox, group)
    # Claim + process any messages from a dead previous server instance
    claimed = await _bus.stream_claim_pending(inbox, group, consumer)
    if claimed:
        logger.info("Redis master watcher: claimed {} pending messages", len(claimed))
        for msg in claimed:
            await _process_inbox_message(
                msg, _bus, inbox, group, master_agent, ws_manager,
                status_path, notification_queue,
            )
    await _bus.flush_outbox("master")

    logger.info(
        "Redis master watcher: reading {} (consumer={})",
        inbox, consumer,
    )

    while True:
        try:
            msgs = await _bus.stream_read_group(inbox, group, consumer, block_ms=5000)
            for msg in msgs:
                await _process_inbox_message(
                    msg, _bus, inbox, group, master_agent, ws_manager,
                    status_path, notification_queue,
                )
        except Exception as _exc:
            logger.warning(
                "Redis master watcher iteration failed (will retry): {}", _exc
            )
            await asyncio.sleep(2)


async def _process_inbox_message(
    msg: dict,
    _bus,
    inbox: str,
    group: str,
    master_agent,
    ws_manager,
    status_path: Path,
    notification_queue,
) -> None:
    """Process a single Redis inbox message for master."""
    data = msg.get("data", {})
    if not isinstance(data, dict):
        return

    msg_type = data.get("type", "")
    msg_id = str(msg.get("id", ""))

    if msg_type != "task_result":
        await _bus.stream_ack(inbox, group, msg_id)
        return

    child_agent = str(data.get("child_agent", "unknown"))
    child_status = str(data.get("status", "done"))
    session_id = str(data.get("session_id", ""))
    raw_result = str(data.get("result", ""))

    def _safety_enqueue() -> bool:
        """Enqueue this Redis payload into notification_queue. Returns True on success.

        Queue convention: result is non-empty only for status=done, error
        non-empty only for status=error. Matches NotifyParentTool's split so
        dedup byte-comparison works.
        """
        try:
            notification_queue.enqueue(
                parent_agent="master",
                child_agent=child_agent,
                status=child_status,
                result=raw_result if child_status == "done" else "",
                error=raw_result if child_status == "error" else "",
                session_id=session_id,
            )
            return True
        except Exception as _enq_exc:
            logger.warning(
                "Redis master watcher: safety enqueue failed: {}", _enq_exc
            )
            return False

    # Fix 1.1: don't ACK when master is busy. Without an ACK, Redis keeps the
    # message in the consumer-group pending list and re-delivers on the next
    # cycle. The safety enqueue also gives the notification watcher a chance
    # to pick it up the moment master idles. Queue dedup handles the
    # double-write if Redis later redelivers.
    if master_agent.is_busy():
        _safety_enqueue()
        return

    # Fix 3.4 (transitional defer): if the notification_queue already has a
    # matching unconsumed entry, let the notification watcher handle it — do
    # not ACK Redis (let it redeliver if the queue path also drops the ball).
    # After Fix 3.1 fully rolls out NotifyParentTool should not emit both
    # paths, so this branch rarely fires.
    if notification_queue.has_matching_unconsumed(
        parent_agent="master",
        child_agent=child_agent,
        status=child_status,
        result=raw_result if child_status == "done" else "",
        error=raw_result if child_status == "error" else "",
        session_id=session_id,
    ):
        logger.debug(
            "Redis master watcher: queue match — deferring to notification watcher"
        )
        return

    logger.info(
        "Redis master watcher: {} ({}) sid={}",
        child_agent, child_status, session_id[:8] if session_id else "<none>",
    )

    task_prompt = (
        f"[Auto-notification via Redis] {child_agent} completed ({child_status}). "
        "Read the sub-agent results via read_task_result if needed, "
        "then write ONE short summary message for the user describing "
        "what was accomplished. Do NOT re-spawn agents, do NOT re-verify "
        "work that is already verified, and do NOT investigate beyond "
        "reading the result text. The chain has already finished — your "
        "only job here is to surface the outcome to the user."
    )

    try:
        async for _ in master_agent.handle_task_stream(
            task=task_prompt,
            source="notification",
            session_id=session_id or None,
        ):
            pass

        # Drain notification_queue so the same session doesn't re-trigger
        notification_queue.drain("master", session_id=session_id or None)

        # Push result to WebSocket
        result_text = (settings.agents_dir / "master" / "RESULT.MD").read_text(
            encoding="utf-8", errors="replace"
        ).strip()
        if result_text:
            if session_id:
                await ws_manager.push_session_event(
                    session_id,
                    {"type": "notification_result", "text": result_text},
                )
                await ws_manager.push_event("task_complete", {
                    "session_id": session_id,
                    "text": result_text,
                    "source": "notification",
                    "agent": "master",
                })
            else:
                await ws_manager.push_event(
                    "notification_result",
                    {"text": result_text, "session_id": ""},
                )
            logger.info(
                "Redis master watcher: pushed result to session={} ({} chars)",
                (session_id or "<none>")[:8], len(result_text),
            )

        # Successful processing — safe to ACK.
        await _bus.stream_ack(inbox, group, msg_id)
        return
    except Exception as _proc_exc:
        # Fix 1.2: re-enqueue on processing failure so notification watcher
        # can retry. Only ACK Redis if the queue path accepted the payload —
        # otherwise leave it pending in Redis for redelivery.
        logger.warning("Redis master watcher: processing failed: {}", _proc_exc)
        if _safety_enqueue():
            await _bus.stream_ack(inbox, group, msg_id)
        else:
            logger.error(
                "Redis master watcher: BOTH processing AND safety enqueue failed for "
                "child={} sid={} — leaving message pending for Redis redelivery.",
                child_agent, session_id[:8] if session_id else "<none>",
            )
        return


def _is_task_already_consumed(agent_name: str) -> bool:
    """Return True if the agent's TASK.MD has a non-empty consumed_at frontmatter.

    Used during startup reconcile to decide whether a queued notification or
    a pending Redis message refers to work that was already processed before
    crash/restart.
    """
    try:
        task_path = settings.agents_dir / agent_name / "TASK.MD"
        if not task_path.exists():
            return False
        content = task_path.read_text(encoding="utf-8")
        m = re.search(r"^consumed_at:\s*(\S.*)$", content, re.MULTILINE)
        return bool(m and m.group(1).strip())
    except Exception:
        return False


async def _startup_resume() -> None:
    """Resume interrupted work after server restart.

    Reads master/RESUME.MD for restart context, checks Redis for pending
    task_result messages from agents that completed during downtime, and
    creates task_queue entries for the dispatcher.
    """
    import uuid
    from app.utils.db import create_queued_task, get_tasks_by_status
    from app.utils.cost_governor import is_autonomous_budget_exhausted

    resumed = 0

    # 1. Check RESUME.MD for restart context
    resume_path = settings.agents_dir / "master" / "RESUME.MD"
    next_action = ""
    resume_session_id = ""
    if resume_path.exists():
        content = resume_path.read_text(encoding="utf-8").strip()
        if content:
            # Parse YAML frontmatter for next_action and session_id
            fm: dict[str, str] = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            fm[k.strip()] = v.strip()
                    next_action = fm.get("next_action", "")
                    resume_session_id = fm.get("session_id", "")

            if next_action:
                task_id = str(uuid.uuid4())
                create_queued_task(
                    id=task_id,
                    prompt=f"[Resume] {next_action}",
                    source="resume",
                    session_id=resume_session_id,
                )
                resumed += 1
                logger.info(
                    "Resumed from RESUME.MD: {} (session={})",
                    next_action,
                    resume_session_id[:8] if resume_session_id else "<none>",
                )

            # Clear RESUME.MD after consuming
            resume_path.write_text("")

    # 2. Check Redis for pending task_result messages in master's inbox
    #    (agents that finished during shutdown/downtime)
    try:
        from app.backend.message_bus import bus as _bus
        if _bus.connected:
            inbox = "agent:master:inbox"
            group = "master_group"
            consumer = f"master_resume_{os.getpid()}"
            await _bus.stream_create_group(inbox, group)
            claimed = await _bus.stream_claim_pending(inbox, group, consumer)
            if claimed:
                logger.info("Startup resume: claimed {} pending messages from Redis inbox", len(claimed))
                from app.backend.services.notification_queue import notification_queue as _nq
                for msg in claimed:
                    data = msg.get("data", {})
                    if not isinstance(data, dict):
                        await _bus.stream_ack(inbox, group, str(msg.get("id", "")))
                        continue
                    msg_type = data.get("type", "")
                    if msg_type == "task_result":
                        child = str(data.get("child_agent", "unknown"))
                        status = str(data.get("status", "done"))
                        result = str(data.get("result", ""))
                        sid = str(data.get("session_id", ""))
                        # Fix 3.3: skip if the child's TASK.MD already has
                        # consumed_at set — this Redis message arrived from
                        # work that was already processed before crash.
                        if _is_task_already_consumed(child):
                            logger.info(
                                "Startup resume: skipping {} ({}) — TASK.MD already consumed",
                                child, status,
                            )
                            await _bus.stream_ack(inbox, group, str(msg.get("id", "")))
                            continue
                        # Enqueue to notification_queue so the watcher picks it up naturally
                        _nq.enqueue(
                            parent_agent="master",
                            child_agent=child,
                            status=status,
                            result=result if status == "done" else "",
                            error=result if status == "error" else "",
                            session_id=sid,
                        )
                        logger.info(
                            "Startup resume: enqueued {} ({}) result for master (sid={})",
                            child, status, sid[:8] if sid else "<none>",
                        )
                    await _bus.stream_ack(inbox, group, str(msg.get("id", "")))
    except Exception as _exc:
        logger.warning("Startup resume: Redis pending check failed: {}", _exc)

    # Fix 3.3: reconcile any pre-existing queue entries whose source TASK.MD
    # is already marked consumed_at. This catches the case where master
    # crashed between mark_task_consumed and queue drain on the prior run.
    try:
        from app.backend.services.notification_queue import notification_queue as _nq_rec
        pending = _nq_rec.pending_entries("master")
        reconciled = 0
        for entry in pending:
            child = entry.get("child_agent", "")
            if child and _is_task_already_consumed(child):
                marked = _nq_rec.mark_consumed_matching(
                    parent_agent="master",
                    child_agent=child,
                    session_id=entry.get("session_id", ""),
                )
                reconciled += marked
        if reconciled:
            logger.info(
                "Startup resume: reconciled {} queue entry(ies) with consumed TASK.MD",
                reconciled,
            )
    except Exception as _exc:
        logger.warning("Startup resume: queue reconcile failed: {}", _exc)

    # 3. If no pending user tasks and budget allows, check goals
    if resumed == 0:
        pending = get_tasks_by_status("pending", limit=1)
        if not pending and not is_autonomous_budget_exhausted():
            goals_path = settings.agents_dir / "master" / "GOALS.MD"
            if goals_path.exists():
                goals_text = goals_path.read_text(encoding="utf-8")
                active_match = re.search(
                    r"## Active\s*\n(.*?)(?=\n## |\Z)", goals_text, re.DOTALL
                )
                if active_match:
                    unchecked = re.findall(r"- \[ \] (.+)", active_match.group(1))
                    if unchecked:
                        top_goal = unchecked[0].strip()
                        task_id = str(uuid.uuid4())
                        create_queued_task(
                            id=task_id,
                            prompt=f"[Goal] {top_goal}",
                            source="goal",
                        )
                        resumed += 1
                        logger.info(f"Startup goal dispatch: '{top_goal}'")

    if resumed:
        logger.info(f"Startup resume: {resumed} task(s) queued")
    else:
        logger.info("Startup resume: nothing to resume")


async def _cron_tick() -> None:
    """Check cron schedule and create task_queue entries for due jobs.

    Uses the cron_parser to read NOTES.MD, check which jobs are due,
    and creates task_queue entries with source="cron" for the dispatcher.
    Falls back to spawning the cron agent for complex jobs.
    """
    from app.utils.cron_parser import parse_schedule, get_due_jobs, load_last_runs, save_last_run
    from app.utils.cost_governor import is_autonomous_budget_exhausted
    from app.utils.db import create_queued_task

    try:
        if is_autonomous_budget_exhausted():
            return

        cron_notes = settings.agents_dir / "cron" / "NOTES.MD"
        if not cron_notes.exists():
            return

        notes_text = cron_notes.read_text(encoding="utf-8")
        jobs = parse_schedule(notes_text)
        if not jobs:
            return

        last_runs = load_last_runs()
        due = get_due_jobs(jobs, last_runs)

        for job in due:
            import uuid
            task_id = str(uuid.uuid4())
            task_text = job.get("task", "")
            assign_to = job.get("assign_to", "master")
            job_id = job.get("id", "unknown")

            create_queued_task(
                id=task_id,
                prompt=f"[Cron: {job_id}] {task_text}",
                source="cron",
                metadata=json.dumps({"cron_job_id": job_id, "assign_to": assign_to}),
            )
            save_last_run(job_id)
            logger.info(f"Cron job '{job_id}' due — created task {task_id[:8]}…")

    except Exception as exc:
        logger.error(f"Cron tick error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.backend.logging_config import setup_logging
    setup_logging()

    # Connect to Redis message bus (non-fatal: agents fall back to outbox if down)
    await bus.connect()

    _cleanup_stale_agent_statuses()

    # Initialize SQLite schema
    from app.utils.db import init_schema, get_tasks_by_status, update_queued_task
    init_schema()

    # Recover stale tasks from previous server run
    stale = get_tasks_by_status("running")
    for task in stale:
        tid = task["id"]
        logger.info(f"Recovering stale task {tid[:8]}… (was running, resetting to pending)")
        update_queued_task(tid, status="pending", started_at=None, assigned_agent=None)

    # Load tool plugins from plugins/ directory
    from app.utils.tools.plugin_loader import load_plugins
    load_plugins()

    # Notification system — load persisted state and start background poller
    from app.backend.services.spawn_registry import registry
    from app.backend.services.notification_queue import notification_queue
    from app.backend.services.notification_poller import create_poller
    from app.backend.relay import relay as message_bus_relay
    registry.load()
    notification_queue.load()
    # Redis pub/sub → WebSocket relay — routes agent events to connected browser clients.
    await message_bus_relay.start()
    # Notification poller: always runs as cross-process safety net.
    # Even when Redis is connected, some subprocess agents may not have
    # a working Redis connection. The poller catches completions via TASK.MD.
    # Redis paths deliver faster; poller deduplicates via notification_queue.
    poller = create_poller(
        settings.agents_dir,
        poll_interval=settings.notification_poll_interval_seconds,
    )
    poller.start()

    # Fix 1.4: run startup resume to completion BEFORE scheduling the live
    # watchers, so they don't race for the same pending Redis messages or
    # queue entries. Latency cost is bounded (a few seconds at most).
    try:
        await _startup_resume()
    except Exception as _resume_exc:
        logger.warning("Startup resume failed (continuing): {}", _resume_exc)

    if bus.connected:
        logger.info("Redis connected — starting Redis master watcher")
        asyncio.ensure_future(_master_redis_watcher())
    asyncio.ensure_future(_master_notification_watcher())

    # Start task dispatcher (background loop that executes queued tasks)
    from app.backend.dispatcher import dispatcher_loop, request_shutdown
    dispatcher_task = asyncio.create_task(dispatcher_loop())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _doctor_tick,
        "interval",
        minutes=settings.doctor_interval_minutes,
        id="doctor_health_check",
    )
    scheduler.add_job(
        _cron_tick,
        "interval",
        minutes=settings.cron_interval_minutes,
        id="cron_scheduler",
    )
    scheduler.add_job(
        _model_manager_tick,
        "interval",
        hours=settings.model_manager_interval_hours,
        id="model_manager_audit",
    )
    scheduler.add_job(
        _indexer_tick,
        "interval",
        minutes=settings.embedding_index_interval_minutes,
        id="indexer",
    )
    scheduler.start()
    # Run initial checks shortly after startup
    loop = asyncio.get_event_loop()
    loop.call_later(5, lambda: asyncio.ensure_future(_doctor_tick()))
    loop.call_later(10, lambda: asyncio.ensure_future(_cron_tick()))
    loop.call_later(15, lambda: asyncio.ensure_future(_model_manager_tick()))
    loop.call_later(20, lambda: asyncio.ensure_future(_indexer_tick()))
    try:
        yield
    finally:
        request_shutdown()
        dispatcher_task.cancel()
        scheduler.shutdown(wait=False)
        poller.stop()
        await message_bus_relay.stop()
        await bus.disconnect()


app = FastAPI(title="YAPOC", version="0.1.0", lifespan=lifespan)

_cors_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.websocket("/ws")(websocket_endpoint)
app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(metrics_router)
app.include_router(files_router)
app.include_router(memory_graph_router)
app.include_router(vault_router)
app.include_router(test_endpoint_router)
app.include_router(webhook_router)
app.include_router(costs_router)
app.include_router(models_router)
app.include_router(stale_tasks_router)
app.include_router(notification_trace_router)
app.include_router(voice_router)
app.include_router(sessions_router)
