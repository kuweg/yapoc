import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

from app.config import settings

router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health():
    return {"status": "ok", "uptime": round(time.time() - _start_time, 2)}


@router.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now(timezone.utc).isoformat()}


def _parse_health_md(path: Path) -> dict:
    """Parse a single HEALTH.MD file and return structured stats."""
    entries = []
    if not path.exists():
        return {"entries": [], "last_check": None, "last_error": None}

    content = path.read_text(encoding="utf-8", errors="replace")
    # Pattern: [YYYY-MM-DD HH:MM] LEVEL: message
    pattern = re.compile(
        r"^\[(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*(?P<level>\w+):?\s*(?P<msg>.*)$",
        re.MULTILINE,
    )

    for m in pattern.finditer(content):
        ts_str = m.group("ts")
        level = m.group("level").upper()
        msg = m.group("msg").strip()
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        entries.append({"timestamp": ts, "level": level, "message": msg})

    if not entries:
        return {"entries": [], "last_check": None, "last_error": None}

    entries.sort(key=lambda e: e["timestamp"])
    last = entries[-1]
    last_error = None
    for e in reversed(entries):
        if e["level"] in ("ERROR", "CRITICAL", "FATAL"):
            last_error = e
            break

    return {
        "entries": entries,
        "last_check": last["timestamp"],
        "last_error": last_error,
    }


@router.get("/health/summary")
async def health_summary():
    """Aggregated health status across all agents."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(hours=24)

    agents: list[dict] = []
    total_errors_1h = 0
    total_errors_24h = 0
    agents_with_errors = 0

    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("base", "shared"):
            continue

        parsed = _parse_health_md(agent_dir / "HEALTH.MD")
        entries = parsed["entries"]

        errors_1h = sum(
            1 for e in entries
            if e["level"] in ("ERROR", "CRITICAL", "FATAL")
            and e["timestamp"] >= one_hour_ago
        )
        errors_24h = sum(
            1 for e in entries
            if e["level"] in ("ERROR", "CRITICAL", "FATAL")
            and e["timestamp"] >= one_day_ago
        )
        warnings_1h = sum(
            1 for e in entries
            if e["level"] == "WARNING" and e["timestamp"] >= one_hour_ago
        )
        warnings_24h = sum(
            1 for e in entries
            if e["level"] == "WARNING" and e["timestamp"] >= one_day_ago
        )

        if errors_24h > 0 or warnings_24h > 0:
            agents_with_errors += 1

        total_errors_1h += errors_1h
        total_errors_24h += errors_24h

        status = "healthy"
        if errors_1h > 0:
            status = "critical"
        elif errors_24h > 0:
            status = "degraded"
        elif warnings_1h > 0:
            status = "warning"

        agents.append({
            "name": agent_dir.name,
            "status": status,
            "last_check": parsed["last_check"].isoformat() if parsed["last_check"] else None,
            "last_error": parsed["last_error"]["message"] if parsed["last_error"] else None,
            "last_error_at": parsed["last_error"]["timestamp"].isoformat() if parsed["last_error"] else None,
            "errors_1h": errors_1h,
            "errors_24h": errors_24h,
            "warnings_1h": warnings_1h,
            "warnings_24h": warnings_24h,
        })

    # Also include Doctor's HEALTH_SUMMARY.MD if available
    summary_path = settings.agents_dir / "doctor" / "HEALTH_SUMMARY.MD"
    doctor_summary = ""
    if summary_path.exists():
        doctor_summary = summary_path.read_text(encoding="utf-8", errors="replace")

    return {
        "generated_at": now.isoformat(),
        "agents": sorted(agents, key=lambda a: (a["errors_24h"], a["warnings_24h"]), reverse=True),
        "summary": {
            "total_agents": len(agents),
            "agents_healthy": sum(1 for a in agents if a["status"] == "healthy"),
            "agents_with_errors": agents_with_errors,
            "total_errors_1h": total_errors_1h,
            "total_errors_24h": total_errors_24h,
        },
        "doctor_summary": doctor_summary,
    }
