"""Stale task watchdog router."""
from __future__ import annotations
import json
import os
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/stale-tasks", tags=["stale-tasks"])

_AGENTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../agents")
)
_SETTINGS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../config/agent-settings.json")
)


def _get_threshold() -> int:
    try:
        with open(_SETTINGS_PATH) as f:
            data = json.load(f)
        return int(data.get("stale_task_threshold_seconds", 600))
    except Exception:
        return 600


def _parse_frontmatter(content: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


@router.get("")
async def list_stale_tasks():
    """Return all agent tasks that have been running longer than the threshold."""
    threshold = _get_threshold()
    now = time.time()
    stale = []

    if not os.path.isdir(_AGENTS_DIR):
        return {"stale_tasks": [], "threshold_seconds": threshold}

    for agent_name in sorted(os.listdir(_AGENTS_DIR)):
        task_path = os.path.join(_AGENTS_DIR, agent_name, "TASK.MD")
        if not os.path.exists(task_path):
            continue
        try:
            with open(task_path) as f:
                content = f.read()
            fm = _parse_frontmatter(content)
            if fm.get("status") != "running":
                continue
            assigned_at_str = fm.get("assigned_at", "")
            if not assigned_at_str:
                continue
            assigned_at = datetime.fromisoformat(
                assigned_at_str.replace("Z", "+00:00")
            )
            elapsed = now - assigned_at.timestamp()
            if elapsed > threshold:
                stale.append(
                    {
                        "agent": agent_name,
                        "status": "running",
                        "assigned_at": assigned_at_str,
                        "elapsed_seconds": round(elapsed),
                        "threshold_seconds": threshold,
                    }
                )
        except Exception:
            continue

    return {"stale_tasks": stale, "threshold_seconds": threshold}
