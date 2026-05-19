import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from loguru import logger
from fastapi.middleware.cors import CORSMiddleware

from app.backend.routers import (
    admin_router,
    agents_router,
    commands_router,
    concilium_router,
    costs_router,
    files_router,
    health_router,
    memory_graph_router,
    metrics_router,
    models_router,
    notification_trace_router,
    sessions_router,
    stale_tasks_router,
    tasks_router,
    test_endpoint_router,
    vault_router,
    voice_router,
    webhook_router,
)
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
    """On server start, reset every non-master agent to a clean baseline.

    Subprocess agents use ``start_new_session=True`` so they survive their
    parent uvicorn dying. When the new backend boots, those orphan processes
    still own a STATUS.json saying ``idle``/``running``/``spawning`` — the
    new backend has no relationship to them. SpawnAgentTool then refuses to
    spawn ("agent already processing") and master must do a manual STATUS.json
    reset to recover (observed live during self-eval test, 6 wasted turns).

    Policy: every non-master agent dir on disk gets its STATUS.json reset to
    ``terminated`` and stale TASK.MD cleared. Any still-alive orphan PID is
    SIGTERM'd best-effort, so the next spawn lands a fresh subprocess.

    Logs a count of cleaned/killed agents at INFO so long-running ops can
    see what got cleaned up at boot.
    """
    cleaned = 0
    orphans_killed = 0
    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("base", "master", "shared"):
            continue
        status_path = agent_dir / "STATUS.json"
        task_path = agent_dir / "TASK.MD"

        if not status_path.exists():
            # No STATUS.json but TASK.MD may be stale — clear it
            if task_path.exists():
                content = task_path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"^status:\s*(pending|running)", content, re.MULTILINE):
                    task_path.write_text("")
            continue

        try:
            status = json.loads(status_path.read_text())
        except Exception:
            continue

        state = status.get("state", "")
        pid = status.get("pid")
        if state not in ("idle", "running", "spawning"):
            continue  # already terminated; nothing to do

        # Orphan: PID alive but parent backend is us (a new process). Disown.
        alive = bool(pid and _pid_alive_local(pid))
        if alive:
            try:
                import os as _os
                import signal as _signal
                _os.kill(pid, _signal.SIGTERM)
                orphans_killed += 1
                logger.info(
                    "cleanup: SIGTERM'd orphan subprocess for {} (PID {})",
                    agent_dir.name, pid,
                )
            except (ProcessLookupError, PermissionError) as _kill_exc:
                logger.debug(
                    "cleanup: could not SIGTERM PID {} for {} ({})",
                    pid, agent_dir.name, _kill_exc,
                )

        status["state"] = "terminated"
        status["task_summary"] = "shutdown: server restart"
        try:
            status_path.write_text(json.dumps(status, indent=2))
        except Exception:
            pass

        # Clear stale TASK.MD frontmatter so the next spawn writes fresh content
        # and the sidebar doesn't show a busy state.
        if task_path.exists():
            try:
                content = task_path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"^status:\s*(pending|running)", content, re.MULTILINE):
                    task_path.write_text("")
            except Exception:
                pass
        cleaned += 1

    if cleaned or orphans_killed:
        logger.info(
            "cleanup: {} agent STATUS.json reset, {} orphan subprocesses SIGTERM'd",
            cleaned, orphans_killed,
        )


async def _doctor_tick() -> None:
    """Run a single Doctor health check (called by APScheduler)."""
    from app.agents.doctor.agent import doctor_agent

    try:
        await doctor_agent.run_health_check()
    except Exception:
        pass  # Doctor logs its own errors


_EVAL_SIG_PATH = Path("data/evaluator_last_signal.json")


def _compute_evaluator_signal_signature() -> str:
    """Hash NON-EVALUATOR observability signals — what get_recent_signals
    would summarize, MINUS the evaluator's own self-induced churn.

    Critical: the signature must reflect external system activity, not the
    eval's own run. If we count cron-source tasks (the eval's own task) or
    evaluator/master HEALTH.MD entries (which the eval writes to), every
    eval invalidates the signature and the gate never fires.

    Components:
      - task_queue: count + max(updated_at) of done/error tasks **whose
        source is NOT in ('cron')** — user/goal/notification etc.
      - HEALTH.MD: total non-empty lines across agents, EXCLUDING evaluator,
        master, and security (those churn during/after every eval).

    Returns a 16-char hex digest. Robust against transient DB errors
    (returns a sentinel that forces a run rather than blocking forever).

    Known limitation: pure UI chat (master answers directly, doesn't queue
    a task or write to a non-excluded agent's HEALTH.MD) is invisible to
    this signature. That's intentional — the gate's job is to prevent
    back-to-back autonomous evals on a quiet system. Users who want a
    fresh eval after chatting can call ``yapoc evaluator-tick`` and the
    "already running" gate is the only filter; or clear the signature file.
    """
    import hashlib
    try:
        from app.utils.db import get_db
        db = get_db()
        row = db.execute(
            """SELECT COUNT(*) AS n,
                      COALESCE(MAX(updated_at), '') AS latest
               FROM task_queue
               WHERE status IN ('done', 'error', 'timeout')
                 AND COALESCE(source, '') NOT IN ('cron')"""
        ).fetchone()
        n = int(row["n"]) if row else 0
        latest = (row["latest"] if row else "") or ""
    except Exception as _db_exc:
        logger.debug("eval-signal: DB read failed ({}); using ts-only signature", _db_exc)
        n, latest = -1, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Exclude agents whose state churns as a side-effect of every eval.
    # (evaluator: writes REPORT.MD; master: runs to spawn evaluator; security:
    # gates every tool call, writes AUDIT.MD.)
    _CHURN_EXCLUDED = {"base", "shared", "evaluator", "master", "security"}
    health_total = 0
    tokens_total = 0  # successful sub-agent activity → bumps total tokens even when no errors
    try:
        for agent_dir in settings.agents_dir.iterdir():
            if not agent_dir.is_dir() or agent_dir.name in _CHURN_EXCLUDED:
                continue
            hp = agent_dir / "HEALTH.MD"
            if hp.exists():
                try:
                    health_total += sum(
                        1 for ln in hp.read_text(encoding="utf-8", errors="ignore").splitlines()
                        if ln.strip()
                    )
                except OSError:
                    pass
            up = agent_dir / "USAGE.json"
            if up.exists():
                try:
                    usage = json.loads(up.read_text(encoding="utf-8"))
                    tokens_total += int(usage.get("total_input_tokens", 0))
                    tokens_total += int(usage.get("total_output_tokens", 0))
                except (OSError, ValueError, KeyError):
                    pass
    except OSError:
        pass

    sig_input = f"tasks={n}|latest={latest}|health={health_total}|tokens={tokens_total}"
    return hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]


def _read_last_eval_signature() -> str | None:
    path = settings.project_root / _EVAL_SIG_PATH
    if not path.exists():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("signature") or "") or None
    except Exception:
        return None


def _write_last_eval_signature(sig: str) -> None:
    path = settings.project_root / _EVAL_SIG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "signature": sig,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("eval-signal: failed to write signature file ({})", exc)


async def _evaluator_tick() -> None:
    """Queue a scheduled self-evaluation task for master to dispatch.

    Runs every ``settings.evaluator_interval_hours``. Three gates, in order:

    1. Daily autonomous budget exhausted → skip.
    2. Evaluator already pending/running for an autonomous source → skip.
    3. **Skip-if-unchanged**: the observability signature hasn't changed
       since the last queued evaluation → skip. This eliminates "evaluator
       reports the same thing again" noise that was driving master into the
       stuck-loop detector via repeat read_task_result calls. The signature
       captures (task_queue done/error count + latest updated_at + total
       HEALTH.MD lines), which is exactly what the evaluator's
       get_recent_signals summarizes.

    The signature file is updated BEFORE queueing so two concurrent ticks
    can't both pass the gate.
    """
    from app.utils.cost_governor import is_autonomous_budget_exhausted
    from app.utils.db import create_queued_task, get_tasks_by_status

    try:
        if is_autonomous_budget_exhausted():
            logger.debug("evaluator_tick: skipped — daily budget exhausted")
            return

        # Don't pile on if an autonomous evaluation is already queued/running.
        for status in ("pending", "running"):
            for t in get_tasks_by_status(status) or []:
                src = (t.get("source") or "").lower()
                prompt = (t.get("prompt") or "")[:100]
                if src in ("cron", "goal") and "evaluator" in prompt and "self-eval" in prompt.lower():
                    logger.debug("evaluator_tick: skipped — eval already {}", status)
                    return

        current_sig = _compute_evaluator_signal_signature()
        last_sig = _read_last_eval_signature()
        if last_sig and current_sig == last_sig:
            logger.info(
                "evaluator_tick: skipped — signals unchanged since last run (sig={})",
                current_sig,
            )
            return
        # Persist before queueing so a concurrent tick observing the same
        # signature doesn't double-queue.
        _write_last_eval_signature(current_sig)

        import uuid
        task_id = str(uuid.uuid4())
        prompt = (
            "Scheduled self-evaluation. spawn_agent('evaluator', "
            "task='Pull get_recent_signals once. Identify top 3 issues. "
            "Write the new round entry to REPORT.MD keeping only new + 1 "
            "prior round. notify_parent with 3-line summary. Stop gathering "
            "at turn 7 max.', context='Scheduled tick — keep it tight.'). "
            "wait_for_agent('evaluator', timeout=240). Surface the 3-line summary "
            "to the morning report."
        )
        create_queued_task(
            id=task_id,
            prompt=prompt,
            source="cron",
            session_id=None,
        )
        logger.info(
            "evaluator_tick: queued scheduled self-evaluation ({}) sig={}",
            task_id[:8], current_sig,
        )
    except Exception as exc:
        logger.warning("evaluator_tick failed: {}", exc)


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


async def _session_digester_tick() -> None:
    """Run the session digester (called by APScheduler).

    Each tick digests at most one session — the oldest candidate without
    a fresh digest. Cycles through long sessions over a few ticks instead
    of bursting LLM calls when many candidates exist simultaneously.
    """
    try:
        from app.backend.session_digester import session_digester_tick
        await session_digester_tick()
    except Exception:
        pass  # digester logs its own errors


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

    # Bug 54 defense: prune Redis consumer registrations whose owning PID is
    # dead before we register our own. Covers the SIGKILL case where the
    # previous backend's shutdown cleanup didn't run. Without this, every
    # ungraceful exit leaks a consumer in master_group.
    if bus.connected:
        try:
            await bus.stream_prune_dead_consumers(
                "agent:master:inbox", "master_group"
            )
        except Exception as _prune_exc:
            logger.warning("Startup consumer prune failed: {}", _prune_exc)

    _cleanup_stale_agent_statuses()

    # If the cleanup signaled crash-recovery (orphan SIGTERMs or stale tasks),
    # rewrite MORNING_REPORT.md so a human waking up sees what happened.
    try:
        from app.backend.morning_report import write_morning_report
        write_morning_report("crash_recovery", {
            "boot_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception as _mr_exc:
        logger.warning("Startup morning_report write failed: {}", _mr_exc)

    # Initialize SQLite schema
    from app.utils.db import init_schema, get_tasks_by_status, update_queued_task
    init_schema()

    # Recover stale tasks from previous server run. Goal-source tasks
    # naturally resume because _check_goals' new duplicate guard sees the
    # pending task and skips re-dispatching the same goal text.
    stale = get_tasks_by_status("running")
    _resumed_goals: list[str] = []
    for task in stale:
        tid = task["id"]
        src = (task.get("source") or "").lower()
        prompt_preview = (task.get("prompt") or "")[:80]
        logger.info(
            "Recovering stale task {} source={} prompt={!r} (running → pending)",
            tid[:8], src, prompt_preview,
        )
        update_queued_task(tid, status="pending", started_at=None, assigned_agent=None)
        if src == "goal":
            _resumed_goals.append(prompt_preview)
    if _resumed_goals:
        logger.info(
            "Goal resumption: {} goal-source task(s) re-queued for pickup: {}",
            len(_resumed_goals), _resumed_goals,
        )

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

    # Start Telegram bot if configured
    if settings.telegram_enabled:
        from app.backend.telegram_bot import TelegramBot
        telegram_bot = TelegramBot(token=settings.telegram_bot_token)
        asyncio.ensure_future(telegram_bot.start())
        logger.info("Telegram bot started (polling mode)")

    # Morning report subscriber — the primary, reliable trigger for autonomous
    # task_complete events. Inline hooks in dispatcher.py + master/agent.py
    # are kept as belt-and-suspenders but were observed to silently miss for
    # some cron-source completions (event loop starvation by sync I/O).
    if bus.connected:
        from app.backend.morning_report_listener import morning_report_subscriber
        asyncio.ensure_future(morning_report_subscriber())

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
    scheduler.add_job(
        _evaluator_tick,
        "interval",
        hours=settings.evaluator_interval_hours,
        id="evaluator_scheduled",
    )
    scheduler.add_job(
        _session_digester_tick,
        "interval",
        minutes=settings.session_digest_interval_minutes,
        id="session_digester",
    )
    scheduler.start()
    # Run initial checks shortly after startup
    loop = asyncio.get_event_loop()
    loop.call_later(5, lambda: asyncio.ensure_future(_doctor_tick()))
    loop.call_later(10, lambda: asyncio.ensure_future(_cron_tick()))
    loop.call_later(15, lambda: asyncio.ensure_future(_model_manager_tick()))
    loop.call_later(20, lambda: asyncio.ensure_future(_indexer_tick()))
    # Run session digester after the indexer so the first pass has fresh data.
    loop.call_later(45, lambda: asyncio.ensure_future(_session_digester_tick()))
    try:
        yield
    finally:
        request_shutdown()
        dispatcher_task.cancel()
        scheduler.shutdown(wait=False)
        poller.stop()
        await message_bus_relay.stop()
        # Bug 54: remove our master consumer registrations from Redis before
        # disconnecting so they don't linger in master_group across restarts.
        # Without this, every `yapoc restart` left a `master_<old_pid>` and
        # `master_resume_<old_pid>` behind. After 5 restarts we saw 93
        # zombie consumers all receiving the same events.
        try:
            inbox = "agent:master:inbox"
            group = "master_group"
            our_pid = os.getpid()
            if bus.connected:
                await bus.stream_delete_consumer(
                    inbox, group, f"master_{our_pid}"
                )
                await bus.stream_delete_consumer(
                    inbox, group, f"master_resume_{our_pid}"
                )
        except Exception as _consumer_cleanup_exc:
            logger.warning(
                "Shutdown: master consumer cleanup failed: {}",
                _consumer_cleanup_exc,
            )
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
app.include_router(commands_router)
app.include_router(concilium_router)
app.include_router(admin_router)
