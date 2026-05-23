"""Observability router — centralized health dashboard endpoints.

Exposes agent health aggregation by reading per-agent HEALTH.MD files.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/health", tags=["observability"])

# ── Regexes for HEALTH.MD parsing ─────────────────────────────────────────

HEALTH_ENTRY_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*(.*)$"
)
LEVEL_RE = re.compile(
    r"^(INFO|ERROR|WARNING|WARN|DEBUG|CRITICAL):\s*(.*)$",
    re.IGNORECASE,
)


# ── Pydantic models ───────────────────────────────────────────────────────

class HealthEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class AgentHealthSummary(BaseModel):
    agent_name: str
    last_error: str | None = None
    error_count_1h: int = 0
    error_count_24h: int = 0
    last_updated: str | None = None


class AgentHealthDetail(AgentHealthSummary):
    entries: list[HealthEntry] = []


# ── Parser ────────────────────────────────────────────────────────────────

def _parse_health_md(content: str) -> list[dict]:
    """Parse HEALTH.MD content into a list of entry dicts.

    Each entry has keys: timestamp (datetime), level (str), message (str).
    Multi-line messages are accumulated until the next timestamped line.
    """
    entries: list[dict] = []
    current: dict | None = None

    for line in content.splitlines():
        m = HEALTH_ENTRY_RE.match(line)
        if m:
            if current is not None:
                entries.append(current)
            ts_str, rest = m.group(1), m.group(2)
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                ts = None

            level_match = LEVEL_RE.match(rest)
            if level_match:
                level = level_match.group(1).lower()
                message = level_match.group(2)
            else:
                level = "info"
                message = rest

            current = {
                "timestamp": ts,
                "level": level,
                "message": message,
            }
        elif current is not None:
            current["message"] += "\n" + line

    if current is not None:
        entries.append(current)

    return entries


def _compute_summary(entries: list[dict]) -> dict:
    """Compute summary fields from parsed entries."""
    now = datetime.now(timezone.utc)
    cutoff_1h = now - timedelta(hours=1)
    cutoff_24h = now - timedelta(hours=24)

    last_error: str | None = None
    error_count_1h = 0
    error_count_24h = 0
    last_updated: str | None = None

    if entries:
        most_recent = entries[-1]["timestamp"]
        if most_recent is not None:
            last_updated = most_recent.isoformat()

    for entry in entries:
        if entry["level"] != "error":
            continue
        ts = entry["timestamp"]
        if ts is None:
            continue
        if last_error is None:
            last_error = entry["message"]
        if ts >= cutoff_1h:
            error_count_1h += 1
        if ts >= cutoff_24h:
            error_count_24h += 1

    return {
        "last_error": last_error,
        "error_count_1h": error_count_1h,
        "error_count_24h": error_count_24h,
        "last_updated": last_updated,
    }


async def _read_health_file(agent_dir: Path) -> list[dict]:
    """Async helper to read and parse an agent's HEALTH.MD."""
    path = agent_dir / "HEALTH.MD"
    if not path.exists():
        return []
    content = await asyncio.to_thread(
        path.read_text, encoding="utf-8", errors="replace"
    )
    return _parse_health_md(content)


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/summary", response_model=list[AgentHealthSummary])
async def get_health_summary() -> list[AgentHealthSummary]:
    """Return a health summary for every discovered agent."""
    agents_dir: Path = settings.agents_dir
    result: list[AgentHealthSummary] = []

    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "__pycache__":
            continue
        entries = await _read_health_file(agent_dir)
        summary = _compute_summary(entries)
        result.append(
            AgentHealthSummary(
                agent_name=agent_dir.name,
                last_error=summary["last_error"],
                error_count_1h=summary["error_count_1h"],
                error_count_24h=summary["error_count_24h"],
                last_updated=summary["last_updated"],
            )
        )

    return result


@router.get("/agents/{agent_name}", response_model=AgentHealthDetail)
async def get_agent_health(agent_name: str) -> AgentHealthDetail:
    """Return detailed health info for a single agent, including recent entries."""
    agents_dir: Path = settings.agents_dir
    agent_dir = agents_dir / agent_name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    entries = await _read_health_file(agent_dir)
    summary = _compute_summary(entries)

    recent_entries = [
        HealthEntry(
            timestamp=e["timestamp"].isoformat() if e["timestamp"] else "",
            level=e["level"],
            message=e["message"],
        )
        for e in entries[-50:]
    ]

    return AgentHealthDetail(
        agent_name=agent_name,
        last_error=summary["last_error"],
        error_count_1h=summary["error_count_1h"],
        error_count_24h=summary["error_count_24h"],
        last_updated=summary["last_updated"],
        entries=recent_entries,
    )


__all__ = ["router"]
