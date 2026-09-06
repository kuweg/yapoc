"""Skill health tracker and demotion ladder for the YAPOC skill system.

Skills are YAML files in ``app/skills/`` (e.g. ``frontend_build.yaml``) with
progressive-disclosure levels: ``level_1`` (one-line summary), ``level_2``
(params/inputs) and ``level_3`` (full step-by-step procedure).

This module backs the "skill verification loop". When a skill is executed at
level_3 and the task that used it fails repeatedly, the skill is auto-demoted
one rung down the ladder: ``level_3`` removed -> ``level_2`` removed ->
``level_1`` removed -> file deleted. A success resets the failure counter.

Run state is persisted to a JSON dict at ``app/skills/.health.json``::

    {"<skill_name>": {
        "consecutive_failures": int,
        "last_used": "<iso timestamp or empty>",
        "last_outcome": "success" | "failure" | ""
    }}

State IO and YAML mutation are wrapped in try/except and log through a
module-level logger so this side channel never crashes its caller.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
import yaml

from app.config import settings

_log = logging.getLogger("skills_health")

HEALTH_DIR: Path = settings.project_root / "app" / "skills"
HEALTH_PATH: Path = HEALTH_DIR / ".health.json"

_EMPTY_ENTRY = {"consecutive_failures": 0, "last_used": "", "last_outcome": ""}


async def _load_state() -> dict:
    """Load the health state dict, starting empty if missing/corrupt."""
    try:
        async with aiofiles.open(HEALTH_PATH, encoding="utf-8") as f:
            raw = await f.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        _log.warning("skills_health: expected dict, got %s; resetting", type(data).__name__)
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 - never crash on corrupt state
        _log.warning("skills_health: failed to read %s (%s); resetting", HEALTH_PATH, exc)
    return {}


async def _save_state(state: dict) -> None:
    """Atomically persist the health state dict (temp file + os.replace)."""
    tmp_path = HEALTH_PATH.with_suffix(HEALTH_PATH.suffix + ".tmp")
    try:
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = HEALTH_PATH.with_name(f".{HEALTH_PATH.name}.{os.getpid()}.tmp")
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(state))
        os.replace(tmp_path, HEALTH_PATH)
    except Exception as exc:  # noqa: BLE001 - non-critical side channel
        _log.warning("skills_health: failed to write state (%s)", exc)


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


async def record_skill_outcome(name: str, success: bool) -> None:
    """Record whether a skill execution succeeded or failed.

    On success the consecutive-failure counter resets to zero; on failure it
    increments. ``last_used`` and ``last_outcome`` are updated accordingly.
    """
    name = str(name)
    try:
        state = await _load_state()
        entry = state.get(name)
        if not isinstance(entry, dict):
            entry = dict(_EMPTY_ENTRY)
        if success:
            entry["consecutive_failures"] = 0
            entry["last_outcome"] = "success"
        else:
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["last_outcome"] = "failure"
        entry["last_used"] = _now_iso()
        state[name] = entry
        await _save_state(state)
        _log.info(
            "skills_health: recorded %s for %s (consecutive_failures=%d)",
            entry["last_outcome"],
            name,
            entry["consecutive_failures"],
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("skills_health: record_skill_outcome failed for %s (%s)", name, exc)


async def check_and_demote(name: str, threshold: int = 3) -> str:
    """Demote a skill one rung if its failure count reaches ``threshold``.

    Returns a human-readable description when a demotion or deletion happened,
    or ``""`` when no action was taken.
    """
    name = str(name)
    try:
        state = await _load_state()
        entry = state.get(name)
        if not isinstance(entry, dict):
            return ""
        failures = int(entry.get("consecutive_failures", 0))
        if failures < threshold:
            return ""

        entry["consecutive_failures"] = 0  # requires a fresh run of failures
        state[name] = entry

        skill_path = HEALTH_DIR / f"{name}.yaml"
        if not skill_path.exists():
            # Missing file: reset the counter and record no demotion.
            entry["last_used"] = _now_iso()
            entry["last_outcome"] = ""
            await _save_state(state)
            _log.info(
                "skills_health: %s reached %d failures but %s is missing; counter reset",
                name,
                threshold,
                skill_path,
            )
            return ""

        async with aiofiles.open(skill_path, encoding="utf-8") as f:
            raw = await f.read()
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            data = {}

        description = ""
        if "level_3" in data:
            del data["level_3"]
            description = f"demoted {name}: removed level_3"
            async with aiofiles.open(skill_path, "w", encoding="utf-8") as f:
                await f.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        elif "level_2" in data:
            del data["level_2"]
            description = f"demoted {name}: removed level_2"
            async with aiofiles.open(skill_path, "w", encoding="utf-8") as f:
                await f.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        elif "level_1" in data:
            skill_path.unlink()
            description = f"deleted skill {name} (no levels left)"
            _log.info("skills_health: deleted skill file %s", skill_path)
        else:
            # File exists but holds no levels we understand; just reset.
            return ""

        entry["last_outcome"] = ""
        state[name] = entry
        await _save_state(state)
        return description
    except Exception as exc:  # noqa: BLE001
        _log.warning("skills_health: check_and_demote failed for %s (%s)", name, exc)
        return ""


async def get_health() -> dict:
    """Return the full health-state dict (for reporting/debugging)."""
    return await _load_state()


async def reset_health(name: str = "") -> None:
    """Reset one skill's health entry, or all of them if ``name`` is empty."""
    name = str(name)
    try:
        state = await _load_state()
        if name:
            state[name] = dict(_EMPTY_ENTRY)
        else:
            for key in list(state):
                state[key] = dict(_EMPTY_ENTRY)
        await _save_state(state)
    except Exception as exc:  # noqa: BLE001
        _log.warning("skills_health: reset_health failed for %r (%s)", name, exc)
