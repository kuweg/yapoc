import asyncio
import json
import os
import re
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.routers import agents_router, files_router, health_router, memory_graph_router, metrics_router, tasks_router, test_endpoint_router, tickets_router, vault_router
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


async def _cron_tick() -> None:
    """Spawn the cron agent with a run-schedule task (called by APScheduler).

    The cron agent is LLM-based, so it runs as a subprocess via SpawnAgentTool.
    It reads its schedule from NOTES.MD and executes due jobs.
    """
    from app.utils.tools.delegation import SpawnAgentTool, _read_status, _pid_alive

    try:
        # Don't spawn cron if it has no schedule (stub/empty NOTES.MD)
        cron_notes = settings.agents_dir / "cron" / "NOTES.MD"
        if not cron_notes.exists() or not cron_notes.read_text(encoding="utf-8").strip():
            return  # No schedule configured — skip to avoid spamming master with empty notifications

        # Don't spawn if cron is already running
        status = _read_status("cron")
        if status and status.get("pid") and _pid_alive(status["pid"]):
            if status.get("state") in ("running", "idle", "spawning"):
                return  # Already active

        spawn = SpawnAgentTool()
        await spawn.execute(
            agent_name="cron",
            task="run-schedule: Execute all due scheduled jobs from your NOTES.MD schedule.",
        )
    except Exception:
        pass  # Cron agent logs its own errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.backend.logging_config import setup_logging
    setup_logging()

    _cleanup_stale_agent_statuses()

    # Initialize SQLite schema
    from app.utils.db import init_schema
    init_schema()

    # Notification system — load persisted state and start background poller
    from app.backend.services.spawn_registry import registry
    from app.backend.services.notification_queue import notification_queue
    from app.backend.services.notification_poller import create_poller
    registry.load()
    notification_queue.load()
    poller = create_poller(settings.agents_dir)
    poller.start()
    asyncio.ensure_future(_master_notification_watcher())

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
        scheduler.shutdown(wait=False)
        poller.stop()


app = FastAPI(title="YAPOC", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(metrics_router)
app.include_router(tickets_router)
app.include_router(files_router)
app.include_router(memory_graph_router)
app.include_router(vault_router)
app.include_router(test_endpoint_router)
