import asyncio
import json
import os
import re
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from loguru import logger
from fastapi.middleware.cors import CORSMiddleware

from app.backend.routers import agents_router, costs_router, files_router, health_router, memory_graph_router, metrics_router, tasks_router, test_endpoint_router, tickets_router, vault_router, webhook_router
from app.backend.websocket import websocket_endpoint
from app.config import settings


def _pid_alive_local(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cleanup_stale_agent_statuses() -> None:
    """On server start, mark dead sub-agents as terminated so stale PIDs don't mislead."""
    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("base", "master"):
            continue
        status_path = agent_dir / "STATUS.json"
        if not status_path.exists():
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
            m = re.search(r"^assigned_by:\s*(.+)$", content, re.MULTILINE)
            trigger_body = re.search(r"\[Process incoming notifications from sub-agents\]", content)
            if not trigger_body:
                continue  # user task — leave it alone
            # Guard: don't interrupt a running master
            try:
                state = json.loads(status_path.read_text()).get("state", "")
                if state == "running":
                    continue
            except Exception:
                pass
            # Consume trigger — set status to avoid re-entry
            content = re.sub(r"^status:\s*pending", "status: consumed", content, flags=re.MULTILINE)
            task_path.write_text(content)
            # Only fire if there are actual pending notifications
            if notification_queue.pending_count("master") == 0:
                continue
            async for _ in master_agent.handle_task_stream(
                task="[Auto-notification] Sub-agent task(s) completed. Process the notification queue.",
                source="notification",
            ):
                pass  # events consumed; result written to RESULT.MD by BaseAgent
        except Exception:
            pass  # never crash the server


async def _startup_resume() -> None:
    """Resume interrupted work after server restart.

    Reads master/RESUME.MD for incomplete tasks and master/GOALS.MD for
    active goals. Creates task_queue entries so the dispatcher picks them up.
    Called via loop.call_later(5, ...) to let agents stabilize first.
    """
    import uuid
    from app.utils.db import create_queued_task, get_tasks_by_status
    from app.utils.cost_governor import is_autonomous_budget_exhausted

    resumed = 0

    # 1. Check RESUME.MD for incomplete tasks
    resume_path = settings.agents_dir / "master" / "RESUME.MD"
    if resume_path.exists():
        content = resume_path.read_text(encoding="utf-8").strip()
        if content:
            # Each non-empty, non-heading line that looks like a task gets queued
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip()
                and not line.strip().startswith("#")
                and not line.strip().startswith("---")
            ]
            for line in lines:
                # Strip markdown list markers
                task_text = re.sub(r"^[-*]\s*(\[.\]\s*)?", "", line).strip()
                if not task_text or len(task_text) < 5:
                    continue
                task_id = str(uuid.uuid4())
                create_queued_task(
                    id=task_id,
                    prompt=f"[Resume] {task_text}",
                    source="resume",
                )
                resumed += 1
                logger.info(f"Resumed task from RESUME.MD: {task_text[:80]}")

            # Clear RESUME.MD after consuming
            resume_path.write_text("")

    # 2. If no pending user tasks and budget allows, check goals
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
                        logger.info(f"Startup goal dispatch: '{top_goal[:80]}'")

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
    registry.load()
    notification_queue.load()
    poller = create_poller(settings.agents_dir)
    poller.start()
    asyncio.ensure_future(_master_notification_watcher())

    # Start task dispatcher (background loop that executes queued tasks)
    from app.backend.dispatcher import dispatcher_loop, request_shutdown
    dispatcher_task = asyncio.create_task(dispatcher_loop())

    # Schedule startup resume after a short delay (let agents stabilize)
    loop = asyncio.get_event_loop()
    loop.call_later(5, lambda: asyncio.ensure_future(_startup_resume()))

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


app = FastAPI(title="YAPOC", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.websocket("/ws")(websocket_endpoint)
app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(metrics_router)
app.include_router(tickets_router)
app.include_router(files_router)
app.include_router(memory_graph_router)
app.include_router(vault_router)
app.include_router(test_endpoint_router)
app.include_router(webhook_router)
app.include_router(costs_router)
