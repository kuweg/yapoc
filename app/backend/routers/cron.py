import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.config import settings
from app.utils.cron_parser import (
    get_failure_count,
    is_cron_disabled,
    load_cron_jobs,
    load_last_runs,
    migrate_cron_jobs_from_notes,
    nl_to_cron,
    save_cron_jobs,
    save_last_run,
)
from app.utils.db import create_queued_task, get_db

router = APIRouter(prefix="/cron", tags=["cron"])


@router.get("")
def list_cron_jobs() -> dict:
    try:
        migrated = migrate_cron_jobs_from_notes()
        if migrated:
            logger.info(f"Migrated {migrated} cron jobs from NOTES.MD")
    except Exception as exc:
        logger.warning(f"Cron migration check failed: {exc}")

    jobs = load_cron_jobs()
    last_runs = load_last_runs() or {}

    enriched_jobs = []
    for job in jobs:
        job_data = dict(job)
        job_id = str(job_data.get("id", "") or "")

        runtime = last_runs.get(job_id)
        if isinstance(runtime, dict):
            last_run = runtime.get("last_run")
            consecutive_failures = int(runtime.get("consecutive_failures", 0) or 0)
            disabled = bool(runtime.get("disabled", False))
        elif isinstance(runtime, str):
            last_run = runtime
            consecutive_failures = get_failure_count(job_id)
            disabled = is_cron_disabled(job_id)
        else:
            last_run = None
            consecutive_failures = get_failure_count(job_id)
            disabled = is_cron_disabled(job_id)

        job_data["last_run"] = last_run
        job_data["consecutive_failures"] = consecutive_failures
        job_data["disabled"] = disabled
        enriched_jobs.append(job_data)

    agents_dir = Path(settings.agents_dir)
    agents = sorted(
        p.name
        for p in agents_dir.iterdir()
        if p.is_dir() and p.name != "__pycache__"
    )

    return {"jobs": enriched_jobs, "agents": agents}


@router.post("")
def create_cron_job(payload: dict) -> dict:
    job_id = str(payload.get("id", "") or "").strip()
    if not job_id:
        raise HTTPException(status_code=422, detail="Field 'id' is required and must be non-empty")

    cron_expr = str(payload.get("cron", "") or "").strip()
    if not cron_expr:
        raise HTTPException(status_code=422, detail="Field 'cron' is required and must be non-empty")

    assign_to = str(payload.get("assign_to", "") or "").strip()
    if not assign_to:
        raise HTTPException(status_code=422, detail="Field 'assign_to' is required and must be non-empty")

    jobs = load_cron_jobs()
    if any(str(job.get("id", "")) == job_id for job in jobs):
        raise HTTPException(status_code=409, detail=f"Cron job with id '{job_id}' already exists")

    normalized_cron = nl_to_cron(cron_expr)

    job = {
        "id": job_id,
        "cron": normalized_cron,
        "task": str(payload.get("task", "") or ""),
        "assign_to": assign_to,
    }

    for optional_key in ("silent", "script", "context_from", "run_only_after"):
        if optional_key in payload:
            job[optional_key] = payload[optional_key]

    jobs.append(job)
    save_cron_jobs(jobs)
    return {"status": "ok", "job": job}


@router.put("/{job_id}")
def update_cron_job(job_id: str, payload: dict) -> dict:
    jobs = load_cron_jobs()

    idx = next((i for i, job in enumerate(jobs) if str(job.get("id", "")) == job_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Cron job '{job_id}' not found")

    updated = dict(jobs[idx])

    if "id" in payload:
        new_id = str(payload.get("id", "") or "").strip()
        if not new_id:
            raise HTTPException(status_code=422, detail="Field 'id' must be non-empty when provided")
        if new_id != job_id and any(str(job.get("id", "")) == new_id for i, job in enumerate(jobs) if i != idx):
            raise HTTPException(status_code=409, detail=f"Cron job with id '{new_id}' already exists")
        updated["id"] = new_id

    if "cron" in payload:
        cron_expr = str(payload.get("cron", "") or "").strip()
        if not cron_expr:
            raise HTTPException(status_code=422, detail="Field 'cron' must be non-empty when provided")
        updated["cron"] = nl_to_cron(cron_expr)

    if "assign_to" in payload:
        assign_to = str(payload.get("assign_to", "") or "").strip()
        if not assign_to:
            raise HTTPException(status_code=422, detail="Field 'assign_to' must be non-empty when provided")
        updated["assign_to"] = assign_to

    if "task" in payload:
        updated["task"] = str(payload.get("task", "") or "")

    for optional_key in ("silent", "script", "context_from", "run_only_after"):
        if optional_key in payload:
            updated[optional_key] = payload[optional_key]

    jobs[idx] = updated
    save_cron_jobs(jobs)
    return {"status": "ok", "job": updated}


@router.delete("/{job_id}")
def delete_cron_job(job_id: str) -> dict:
    jobs = load_cron_jobs()
    remaining = [job for job in jobs if str(job.get("id", "")) != job_id]

    if len(remaining) == len(jobs):
        raise HTTPException(status_code=404, detail=f"Cron job '{job_id}' not found")

    save_cron_jobs(remaining)
    return {"status": "ok"}


@router.post("/{job_id}/run")
def run_cron_job_now(job_id: str) -> dict:
    jobs = load_cron_jobs()
    job = next((j for j in jobs if str(j.get("id", "")) == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Cron job '{job_id}' not found")

    assign_to = str(job.get("assign_to", "") or "").strip()
    if not assign_to:
        raise HTTPException(status_code=422, detail=f"Cron job '{job_id}' has empty assign_to")

    task = str(job.get("task", "") or "")
    task_id = str(uuid.uuid4())
    metadata = json.dumps({"cron_job_id": job_id, "assign_to": assign_to})

    create_queued_task(
        id=task_id,
        session_id=None,
        prompt=f"[Cron: {job_id}] {task}",
        source="cron",
        metadata=metadata,
    )

    save_last_run(job_id)
    return {"status": "ok", "task_id": task_id}


@router.get("/history")
def cron_history() -> dict:
    try:
        db = get_db()
        rows = db.execute(
            "SELECT id, prompt, status, source, assigned_agent, cost_usd, created_at, completed_at, error "
            "FROM task_queue WHERE metadata LIKE ? ORDER BY created_at DESC LIMIT 200",
            (f'%"cron_job_id"%',),
        ).fetchall()

        history = []
        for row in rows:
            if hasattr(row, "keys"):
                history.append({k: row[k] for k in row.keys()})
            else:
                history.append(dict(zip(["id", "prompt", "status", "source", "assigned_agent", "cost_usd", "created_at", "completed_at", "error"], tuple(row))))

        return {"history": history}
    except Exception as exc:
        logger.warning(f"Failed to load cron history: {exc}")
        return {"history": []}
