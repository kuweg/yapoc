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
    artifacts_router,
    commands_router,
    concilium_router,
    costs_router,
    cron_router,
    drive_oauth_router,
    files_router,
    graph_router,
    health_router,
    link_previews_router,
    memory_graph_router,
    mcp_router,
    mcp_servers_router,
    metrics_router,
    models_router,
    notification_trace_router,
    observability_router,
    plugins_router,
    pptx_router,
    sessions_router,
    skills_router,
    stale_tasks_router,
    tasks_router,
    test_endpoint_router,
    uploads_router,
    vault_router,
    notes_router,
    voice_router,
    webhook_router,
)
from app.backend.websocket import websocket_endpoint
from app.backend.message_bus import bus
from app.backend.services.graph_events import graph_event_bus
from app.config import settings
from app.utils.runtime_identity import PROCESS_IDENTITY


def _pid_alive_local(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cleanup_stale_agent_statuses() -> list[str]:
    """Journal interrupted assignments; never delete a child's unfinished work."""
    import psutil
    from app.utils.frontmatter import parse_frontmatter
    recovered = []
    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in {"base", "master", "shared"}:
            continue
        task_path, status_path = agent_dir / "TASK.MD", agent_dir / "STATUS.json"
        content = task_path.read_text(encoding="utf-8") if task_path.exists() else ""
        fields, body = parse_frontmatter(content)
        try:
            status = json.loads(status_path.read_text()) if status_path.exists() else {}
        except (ValueError, OSError):
            status = {}
        if fields.get("status") not in {"pending", "running"} and status.get("state") not in {"running", "spawning", "idle"}:
            continue
        archive = settings.project_root / "data" / "recovery" / agent_dir.name
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        # Write before signalling or changing state. Includes original request,
        # ownership, and process identity so a continuation can inspect it.
        with (archive / f"{stamp}.json").open("w", encoding="utf-8") as f:
            json.dump({"task": content, "status": status}, f)
            f.flush()
            os.fsync(f.fileno())
        pid = status.get("pid")
        if pid:
            try:
                proc = psutil.Process(pid)
                cmd = proc.cmdline()
                matching = "app.agents.base.runner_entry" in cmd and "--agent" in cmd and cmd[cmd.index("--agent") + 1] == agent_dir.name
                matching = matching and Path(proc.cwd()).resolve() == settings.project_root.resolve()
                if matching:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=2)
                        except psutil.TimeoutExpired:
                            logger.warning("Agent {} survived shutdown; preserving its files", agent_dir.name)
                            continue
            except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError, OSError):
                pass
        if fields.get("status") in {"pending", "running"}:
            fields["status"] = "interrupted"
            fields["interrupted_at"] = datetime.now(timezone.utc).isoformat()
            task_path.write_text("---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n" + body, encoding="utf-8")
        status.update(state="interrupted", task_summary=status.get("task_summary", ""))
        status_path.write_text(json.dumps(status), encoding="utf-8")
        recovered.append(agent_dir.name)
    return recovered


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
    """Scheduled fallback indexer tick."""
    from app.utils.indexer import indexer_tick
    await indexer_tick(reason="scheduled_fallback")


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


async def _goal_proposer_tick() -> None:
    """Promote persistent evaluator signals to ``## Proposed`` goals.

    Runs every ``settings.goal_proposer_interval_hours``. Idempotent
    by signal_id and gated by ``settings.goal_proposer_max_per_day``,
    so a chatty evaluator can't flood GOALS.MD. Proposals land in
    ``## Proposed`` (not ``## Active``) so master's idle-check doesn't
    pick them up automatically — promotion is a deliberate user action.
    """
    try:
        from app.utils.goal_proposer import propose_goals
        result = await asyncio.to_thread(propose_goals)
        if result.get("proposed", 0) > 0:
            logger.info(
                "goal_proposer: wrote {} proposal(s) (persistent={}, dupes={}, cap-skip={})",
                result["proposed"], result.get("persistent", 0),
                result.get("skipped_duplicate", 0), result.get("skipped_daily_cap", 0),
            )
    except Exception:
        logger.exception("goal_proposer tick failed")


async def _master_notification_watcher() -> None:
    """Dispatch persisted child results independently of mutable TASK.MD triggers."""
    from app.backend.services.notification_delivery import queue_pending_notifications
    while True:
        try:
            queue_pending_notifications()
        except Exception:
            logger.exception("Notification handoff failed; retaining inputs for retry")
        await asyncio.sleep(3)


async def _master_redis_watcher() -> None:
    """Background task: read master's Redis inbox for child-agent results.

    Child agents publish ``task_result`` to ``agent:master:inbox`` on
    completion. Master has no AgentRunner, so this watcher fills that role
    for Redis-delivered notifications.

    Persists notifications before ACK; periodically reclaims pending messages.
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
    await _bus.flush_outbox("master")

    logger.info(
        "Redis master watcher: reading {} (consumer={})",
        inbox, consumer,
    )

    while True:
        try:
            pending = await _bus.stream_claim_pending(inbox, group, consumer)
            msgs = pending + await _bus.stream_read_group(inbox, group, consumer, block_ms=5000)
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
    if data.get("type") == "task_result":
        status = str(data.get("status", "done"))
        notification_queue.enqueue(
            parent_agent="master", child_agent=str(data.get("child_agent", "unknown")),
            status=status, result=str(data.get("result", "")) if status == "done" else "",
            error=str(data.get("error") or data.get("result", "")) if status != "done" else "",
            session_id=str(data.get("session_id") or ""), task_id=str(data.get("task_id") or ""),
            parent_task_id=str(data.get("parent_task_id") or ""),
        )
    # Enqueue is fsynced and raises on failure: ACK only after durable handoff.
    await _bus.stream_ack(inbox, group, str(msg.get("id", "")))


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
            from app.utils.frontmatter import parse_frontmatter_fields
            fm = parse_frontmatter_fields(content)

            # New writers JSON-encode multiline values inside frontmatter.
            # Legacy plain scalar values remain readable.
            for key in ("next_action", "session_id"):
                value = fm.get(key, "")
                if value.startswith('"'):
                    try:
                        fm[key] = json.loads(value)
                    except (ValueError, TypeError):
                        pass
            next_action = fm.get("next_action", "")
            resume_session_id = fm.get("session_id", "")
            from app.utils.db import get_queued_task
            origin_id = fm.get("origin_task_id", "")
            origin = get_queued_task(origin_id) if origin_id else None
            # Compatibility with restart files written by the old tool factory:
            # recover from the explicit originating run, never the latest chat.
            resume_session_id = (origin or {}).get("session_id") or resume_session_id
            # Unowned service work remains sessionless.

            if next_action:
                # Session checkpointing: if this resume belongs to a session
                # that was compacted before the crash, hydrate the prompt with
                # the pre-crash context so master doesn't start from a blank
                # slate (Fix 5: session checkpointing).
                resume_prompt = f"[Resume] {next_action}"
                if resume_session_id:
                    try:
                        from app.cli.sessions import read_summary
                        summary = read_summary(resume_session_id)
                        if summary:
                            anchor = summary.get("anchor", {}).get("content", "")
                            synth = summary.get("synth", {}).get("content", "")
                            if anchor or synth:
                                resume_prompt += (
                                    f"\n\n[SESSION CONTEXT FROM BEFORE RESTART]\n"
                                    f"Original task: {anchor[:400]}\n"
                                    f"Progress summary: {synth[:1200]}"
                                )
                    except Exception as _sum_exc:
                        logger.debug(
                            "Startup resume: failed to load session summary ({})",
                            _sum_exc,
                        )

                    # Restore the frozen working transcript captured by
                    # server_restart. The compaction summary above is lossy and
                    # only exists if a compact happened; this is the actual
                    # conversation the task was in the middle of.
                    try:
                        from app.utils.conversation_store import load as _load_conv

                        frozen = _load_conv(resume_session_id)
                        if frozen:
                            tail = frozen
                            resume_prompt += (
                                "\n\n[WORKING CONTEXT RESTORED FROM BEFORE RESTART]\n"
                                f"{tail}"
                            )
                            logger.info(
                                "Startup resume: restored {} chars of working context "
                                "for session {}",
                                len(tail), resume_session_id[:8],
                            )
                    except Exception as _conv_exc:
                        logger.debug(
                            "Startup resume: no conversation snapshot ({})", _conv_exc
                        )

                # A crash after enqueue but before consuming RESUME.MD must
                # not create a second copy of the same recovery task.
                task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, content))
                from app.utils.db import get_queued_task
                existing_resume = get_queued_task(task_id)
                if not existing_resume:
                    create_queued_task(
                        id=task_id,
                        prompt=resume_prompt,
                        source="resume",
                        session_id=resume_session_id,
                        metadata=json.dumps({"origin_task_id": origin_id}),
                    )
                elif resume_session_id and existing_resume.get("session_id") in {None, "", task_id}:
                    from app.utils.db import update_queued_task
                    update_queued_task(task_id, session_id=resume_session_id)
                origin_id = fm.get("origin_task_id", "")
                if origin_id and origin_id != task_id:
                    from app.utils.db import update_queued_task
                    origin = get_queued_task(origin_id)
                    if origin and origin["status"] in {"pending", "running", "interrupted"}:
                        update_queued_task(origin_id, status="superseded", error="Continuing after restart", completed_at=datetime.now(timezone.utc).isoformat())
                resumed += 1
                logger.info(
                    "Resumed from RESUME.MD: {} (session={})",
                    next_action,
                    resume_session_id[:8] if resume_session_id else "<none>",
                )

            # Mark RESUME.MD consumed rather than blanking it. The resumed
            # task starts moments later and master reads this file as its first
            # move — finding it EMPTY made it narrate "RESUME.MD is empty, no
            # pending work" in the same turn whose prompt is "[Resume] <action>",
            # contradicting itself to the user. A consumed marker answers the
            # read honestly without re-triggering on the next boot (the parser
            # above only acts on a `next_action:` field, which this omits).
            consumed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            resume_path.write_text(
                "---\n"
                f"consumed_at: {consumed_at}\n"
                f"consumed_by_task: {task_id if next_action else ''}\n"
                "---\n\n"
                "## Already consumed\n"
                "This resume was dispatched at startup and is the task you are "
                "running now. There is no *additional* pending work here — your "
                "current task IS the resume action. Do not report this file as "
                "empty or as evidence that nothing was pending.\n"
                + (f"\nResumed action: {next_action}\n" if next_action else "")
            )

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
                        tid = str(data.get("task_id", ""))
                        # Enqueue to notification_queue so the watcher picks it up naturally
                        _nq.enqueue(
                            parent_agent="master",
                            child_agent=child,
                            status=status,
                            result=result if status == "done" else "",
                            error=result if status == "error" else "",
                            session_id=sid,
                            task_id=tid,
                            parent_task_id=str(data.get("parent_task_id") or ""),
                        )
                        logger.info(
                            "Startup resume: enqueued {} ({}) result for master (sid={})",
                            child, status, sid[:8] if sid else "<none>",
                        )
                    await _bus.stream_ack(inbox, group, str(msg.get("id", "")))
    except Exception as _exc:
        logger.warning("Startup resume: Redis pending check failed: {}", _exc)

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


def _latest_cron_result(db, cron_job_id) -> str | None:
    """Return the most recent done result text for a cron job, or None.

    Uses a LIKE match on the serialized metadata to avoid requiring SQLite
    JSON1 support. Ordered by completed_at DESC so the latest done result wins.
    """
    try:
        row = db.execute(
            "SELECT result, completed_at FROM task_queue "
            "WHERE status='done' AND metadata LIKE ? "
            "ORDER BY completed_at DESC LIMIT 1",
            (f'%"cron_job_id": "{cron_job_id}"%',),
        ).fetchone()
        if row is None:
            return None
        result = row["result"]
        return result if (result or "") else None
    except Exception:
        return None


def _result_newer_than_last_run(upstream_result, last_runs, job_id) -> bool:
    """Decide whether upstream context should be included for a cron job.

    _latest_cron_result doesn't return completed_at, so we fall back to
    including context whenever there is a non-None result (the LIKE ordering
    already yields the most recent done result, which is adequate as a safety
    guard). A job with no recorded last_run always includes fresh context.
    """
    return upstream_result is not None


async def _memory_decay_tick() -> None:
    """Archive MEMORY.MD entries older than the decay window to cold storage.

    Without this the decay module was dead code: it could archive, but nothing
    ever asked it to, so hot memory kept growing.
    """
    from app.utils.memory_decay import archive_stale_memory, archive_stale_shared_knowledge

    max_age = int(getattr(settings, "memory_decay_days", 30) or 30)
    memory_root = settings.project_root / "app" / "memory" / "agents"
    if not memory_root.is_dir():
        return

    def _sweep() -> dict[str, int]:
        # archive_stale_memory works one agent at a time; sweep every agent
        # that has a memory file.
        totals: dict[str, int] = {}
        for agent_dir in sorted(memory_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            try:
                res = archive_stale_memory(agent_dir.name, max_age_days=max_age)
            except Exception as exc:  # one bad agent must not stop the sweep
                logger.debug("memory decay: {} failed ({})", agent_dir.name, exc)
                continue
            n = int((res or {}).get("archived_entries") or (res or {}).get("archived") or 0)
            if n:
                totals[agent_dir.name] = n
        return totals

    try:
        totals = await asyncio.to_thread(_sweep)
        if totals:
            logger.info(
                "memory decay: archived {} entries across {} agent(s) — {}",
                sum(totals.values()), len(totals),
                ", ".join(f"{k}:{v}" for k, v in totals.items()),
            )
    except Exception as exc:
        logger.warning("memory decay tick failed: {}", exc)

    # Also decay the always-on shared store (injected into every agent's
    # context every turn, so pruning it has a direct per-turn token cost).
    try:
        shared_res = await asyncio.to_thread(
            archive_stale_shared_knowledge, max_age_days=max_age
        )
        n = int((shared_res or {}).get("archived") or 0)
        if n:
            logger.info("memory decay: archived {} shared KNOWLEDGE.MD entries", n)
    except Exception as exc:
        logger.warning("memory decay (shared) failed: {}", exc)


async def _cron_tick() -> None:
    """Check cron schedule and create task_queue entries for due jobs.

    Reads jobs from the dedicated cron store (data/cron_jobs.json, migrated
    from the legacy cron agent's NOTES.MD on first run), checks which are due,
    and creates task_queue entries with source="cron" for the dispatcher.

    Supports script jobs (not blocked by budget), silent jobs, and
    context chaining via context_from / run_only_after.
    """
    from app.utils.cron_parser import (
        migrate_cron_jobs_from_notes,
        load_cron_jobs,
        get_due_jobs,
        load_last_runs,
        save_last_run,
        is_cron_disabled,
    )
    from app.utils.cost_governor import (
        is_autonomous_budget_exhausted,
        is_total_budget_exhausted,
        get_total_spend_today,
    )
    from app.utils.db import create_queued_task, get_db

    try:
        migrate_cron_jobs_from_notes()
        jobs = load_cron_jobs()
        if not jobs:
            return

        last_runs = load_last_runs()
        due = get_due_jobs(jobs, last_runs)

        # Escalation ladder: a job auto-disabled after consecutive failures is
        # skipped entirely (its cron_runs.json entry has disabled=True).
        due = [j for j in due if not is_cron_disabled(j.get("id", ""))]
        if not due:
            return

        # Global daily spend cap. Distinct from the autonomous-only budget
        # checked below: this one covers ALL spend, so a heavy interactive day
        # also holds off scheduled work overnight. Script jobs are exempt —
        # they run no model.
        if is_total_budget_exhausted():
            spent = get_total_spend_today()
            agent_jobs = [j for j in due if not j.get("script")]
            if agent_jobs:
                logger.warning(
                    "Cron: daily total budget exhausted (${:.2f} today) — holding "
                    "{} agent job(s); script jobs still run.",
                    spent, len(agent_jobs),
                )
            due = [j for j in due if j.get("script")]
            if not due:
                return

        # Split due jobs into script jobs (skip budget gate) and agent jobs.
        script_due = [j for j in due if j.get("script")]
        agent_due = [j for j in due if not j.get("script")]

        import uuid

        # STEP 2 — Script jobs are processed unconditionally (never budget-blocked).
        for job in script_due:
            task_id = str(uuid.uuid4())
            job_id = job.get("id", "unknown")
            silent = bool(job.get("silent"))
            script = job.get("script") or ""
            script_meta = json.dumps(
                {"cron_job_id": job_id, "script": script, "silent": silent, "script": True}
            )
            create_queued_task(
                id=task_id,
                prompt=f"[Cron: {job_id}] {script}",
                source="script",
                metadata=script_meta,
            )
            save_last_run(job_id)
            logger.info(f"Cron job '{job_id}' due — created script task {task_id[:8]}…")

        # Agent jobs respect the autonomous budget gate.
        if is_autonomous_budget_exhausted():
            if not agent_due:
                return
            logger.info("Skipping agent cron jobs (budget exhausted)")
            return

        db = get_db()

        # STEPS 3-4 — Context chaining + create agent task.
        for job in agent_due:
            task_id = str(uuid.uuid4())
            task_text = job.get("task", "")
            assign_to = job.get("assign_to", "master")
            job_id = job.get("id", "unknown")

            silent = bool(job.get("silent"))
            context_from = job.get("context_from")
            run_only_after = bool(job.get("run_only_after"))

            upstream_result = None
            if context_from:
                upstream_result = _latest_cron_result(db, context_from)

            if run_only_after and not upstream_result:
                logger.info(
                    f"Cron job '{job_id}' deferred — {context_from} has no done result yet"
                )
                continue

            base_prompt = f"[Cron: {job_id}] {task_text}"
            if upstream_result and _result_newer_than_last_run(upstream_result, last_runs, job_id):
                base_prompt = (
                    f"[Cron: {job_id}] {task_text}\n\n"
                    f"[FROM {context_from}]\n{upstream_result[:2000]}"
                )

            meta = {"cron_job_id": job_id, "assign_to": assign_to}
            if silent:
                meta["silent"] = True
            create_queued_task(
                id=task_id,
                prompt=base_prompt,
                source="cron",
                metadata=json.dumps(meta),
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

    # Start graph event bus
    await graph_event_bus.start()

    # Relay graph events published by sub-agent processes onto this process's
    # bus, so /ws/graph shows the whole delegation chain (planning → builder,
    # …) and not just master's own hops.
    async def _graph_relay() -> None:
        from app.backend.services.graph_events import GRAPH_CHANNEL

        while True:
            try:
                async for msg in bus.subscribe(GRAPH_CHANNEL):
                    payload = msg.get("data")
                    if isinstance(payload, dict):
                        await graph_event_bus.ingest_relayed(payload)
            except asyncio.CancelledError:
                raise
            except Exception as _relay_exc:
                logger.warning("Graph relay dropped, retrying in 5s: {}", _relay_exc)
            await asyncio.sleep(5)

    _graph_relay_task = asyncio.create_task(_graph_relay())

    _stale_agent_names = _cleanup_stale_agent_statuses()

    # Reconcile git checkpoints orphaned by a crash mid-task. An agent
    # checkpoint only exists if a sub-agent was spawned but never reached a
    # terminal status (done/error) — i.e. the backend died mid-mutation and
    # half-applied changes + the pre-change SHA are still on disk. Roll them
    # back so a retry starts from a clean tree. This closes the crash gap that
    # _cleanup_stale_agent_statuses does not cover (it only clears TASK.MD/STATUS).
    from app.backend.git_checkpoint_reconcile import reconcile_stale_checkpoints
    try:
        _reconciled = await reconcile_stale_checkpoints(_stale_agent_names)
        if _reconciled:
            logger.info("Reconciled stale git checkpoints for agents: {}", _reconciled)
    except Exception as _rec_exc:
        logger.warning("Startup stale-checkpoint reconcile failed: {}", _rec_exc)

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
    from app.agents.master.agent import master_agent
    master_agent._write_status("idle")

    from app.backend.services.recovery import recover_interrupted_tasks
    recovered_runs = recover_interrupted_tasks()
    logger.info("Recovered {} interrupted queue runs", len(recovered_runs))

    # Load tool plugins from plugins/ directory
    from app.utils.tools.plugin_loader import load_plugins
    load_plugins()

    # Start MCP host layer — connect external MCP servers (e.g. Playwright)
    # and register their tools into TOOL_REGISTRY. Non-fatal: a missing mcp
    # SDK or failed server connection logs a warning and continues.
    # connect() is async (the mcp SDK's stdio_client is an async context
    # manager), so we await it here inside the running lifespan loop.
    try:
        from app.utils.mcp.host import mcp_host_manager
        from app.utils.mcp.registry import register_server_tools
        await mcp_host_manager.connect()
        _mcp_registered = await register_server_tools(mcp_host_manager)
        if _mcp_registered:
            logger.info(
                "MCP: registered {} tool(s) from external servers", _mcp_registered
            )
    except Exception as _mcp_exc:
        logger.warning("MCP host startup failed (continuing): {}", _mcp_exc)

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

    # Start Telegram bot if configured.
    # KEEP A HANDLE: previously this was a fire-and-forget asyncio.ensure_future
    # with no reference saved, so the shutdown block below couldn't stop it.
    # On SIGTERM the lifespan would tear down the rest of the app while the
    # bot kept long-polling Telegram in the background, blocking uvicorn from
    # exiting cleanly. Meanwhile process_restart / yapoc restart had already
    # spawned the *new* uvicorn — both bots ended up polling the same token
    # and the user saw 2x / 3x message processing.
    telegram_bot = None
    telegram_task = None
    if settings.telegram_enabled:
        from app.backend.telegram_bot import TelegramBot, set_telegram_bot_instance
        telegram_bot = TelegramBot(token=settings.telegram_bot_token)
        set_telegram_bot_instance(telegram_bot)
        telegram_task = asyncio.create_task(telegram_bot.start())
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
        _memory_decay_tick,
        "interval",
        hours=getattr(settings, "memory_decay_interval_hours", 6),
        id="memory_decay",
    )
    scheduler.add_job(
        _indexer_tick,
        "interval",
        minutes=10,
        id="indexer",
    )
    scheduler.add_job(
        _evaluator_tick,
        "interval",
        minutes=settings.evaluator_interval_minutes,
        id="evaluator_scheduled",
    )
    scheduler.add_job(
        _session_digester_tick,
        "interval",
        minutes=settings.session_digest_interval_minutes,
        id="session_digester",
    )
    scheduler.add_job(
        _goal_proposer_tick,
        "interval",
        hours=settings.goal_proposer_interval_hours,
        id="goal_proposer",
    )
    if settings.github_enabled and settings.github_poll_interval_seconds > 0:
        from app.utils.github.observability import check_health
        scheduler.add_job(check_health, 'interval', seconds=max(300, settings.github_poll_interval_seconds),
                          id='github_health', max_instances=1, coalesce=True)
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
        from app.backend.services.universes import shutdown as stop_universes
        await stop_universes()
        dispatcher_task.cancel()
        from app.backend.dispatcher import stop_running_tasks
        await stop_running_tasks()
        scheduler.shutdown(wait=False)
        poller.stop()
        _graph_relay_task.cancel()
        await graph_event_bus.stop()
        await message_bus_relay.stop()

        # Shut the Telegram bot down BEFORE anything else awaitable so the
        # 30s long-poll doesn't keep uvicorn alive past the restart window.
        # bot.stop() force-closes the httpx client which aborts the in-flight
        # getUpdates immediately and the polling loop exits within ~5s.
        if telegram_bot is not None:
            try:
                await telegram_bot.stop()
            except Exception as _tg_stop_exc:
                logger.warning("Telegram bot stop() failed: {}", _tg_stop_exc)
        if telegram_task is not None:
            telegram_task.cancel()
            try:
                await telegram_task
            except (asyncio.CancelledError, Exception):
                pass
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
        # Shut down MCP host layer (close stdio subprocess + sessions).
        # disconnect() is async in MCPHostManager.
        try:
            from app.utils.mcp.host import mcp_host_manager
            await mcp_host_manager.disconnect()
        except Exception:
            pass
        await bus.disconnect()


app = FastAPI(title="YAPOC", version="0.1.0", lifespan=lifespan)
from app.backend.access import AccessMiddleware, router as access_router
app.add_middleware(AccessMiddleware)
app.include_router(access_router)

_cors_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.websocket("/ws")(websocket_endpoint)
from app.backend.routers.github import router as github_router
from app.backend.routers.universes import router as universes_router
app.include_router(universes_router)
app.include_router(github_router)
app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(artifacts_router)
app.include_router(metrics_router)
app.include_router(files_router)
app.include_router(uploads_router)
app.include_router(memory_graph_router)
app.include_router(vault_router)
app.include_router(notes_router)
app.include_router(test_endpoint_router)
app.include_router(webhook_router)
app.include_router(costs_router)
app.include_router(models_router)
app.include_router(stale_tasks_router)
app.include_router(notification_trace_router)
app.include_router(voice_router)
app.include_router(sessions_router)
app.include_router(skills_router)
app.include_router(commands_router)
app.include_router(graph_router)
app.include_router(concilium_router)
app.include_router(admin_router)
app.include_router(mcp_router)
app.include_router(mcp_servers_router)
app.include_router(plugins_router)
app.include_router(pptx_router)
app.include_router(cron_router)
app.include_router(drive_oauth_router)
app.include_router(link_previews_router)

# Release installs serve the prebuilt UI without Node or a Vite process.
from app.backend.dashboard import mount_dashboard
mount_dashboard(app, settings.project_root / "app" / "frontend" / "dist")
