"""Read-only checkpoints for shared-workspace tasks.

Verification remains available. Automatic commit and rollback refuse shared
workspace ownership: a dirty-file difference cannot identify who edited it.
Handles remain available for deliberate recovery in an isolated workspace.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger as _log

from app.config import settings


_GIT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class CheckpointHandle:
    sha: str                       # HEAD SHA at snapshot time ("" if disabled)
    label: str                     # "master->builder:add-tool-X"
    spawned_agent: str
    spawned_at: str                # ISO8601 UTC
    # Paths the user already had dirty BEFORE the agent ran. These are
    # excluded from autocommit and from rollback — the user owns them.
    # Stored as a tuple for hashability (dataclass is frozen).
    baseline_dirty: tuple = ()
    enabled: bool = True           # False when settings.git_autocheckpoint_enabled is off

    def to_dict(self) -> dict:
        d = asdict(self)
        d["baseline_dirty"] = list(self.baseline_dirty)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CheckpointHandle":
        baseline = d.get("baseline_dirty", [])
        if isinstance(baseline, list):
            baseline = tuple(baseline)
        return cls(
            sha=d.get("sha", ""),
            label=d.get("label", ""),
            spawned_agent=d.get("spawned_agent", ""),
            spawned_at=d.get("spawned_at", ""),
            baseline_dirty=baseline,
            enabled=d.get("enabled", True),
        )


async def _git(*args: str, check: bool = True, timeout: float = 10.0) -> tuple[int, str, str]:
    """Run `git <args>` async, return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(settings.project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"git {' '.join(args)} timed out after {timeout}s")
    # NOTE: rstrip only — leading whitespace matters for `git status --porcelain`
    # whose lines may start with a space (unstaged column).
    stdout = stdout_b.decode("utf-8", errors="replace").rstrip("\n\r")
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    rc = proc.returncode or 0
    if check and rc != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (rc={rc}): {stderr or stdout}")
    return rc, stdout, stderr


def _parse_porcelain(porcelain_output: str) -> set[str]:
    """Convert `git status --porcelain` lines to a set of path strings.

    Each line is `XY <path>` where XY is the 2-char status flag. Renamed
    entries (`R  old -> new`) are recorded under the new path.
    """
    paths: set[str] = set()
    for line in porcelain_output.splitlines():
        if not line or len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.add(rest.strip())
    return paths


async def snapshot_state(label: str, agent: str) -> CheckpointHandle:
    """Record HEAD SHA + the set of paths already dirty BEFORE this agent runs.

    Dirty paths are diagnostic context only; they do not establish ownership.
    Shared-workspace commit/rollback are refused even when enabled.

    Returns a disabled handle when autocheckpoint is off — the caller path is
    unchanged; verify/commit/rollback no-op on a disabled handle.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not settings.git_autocheckpoint_enabled:
        return CheckpointHandle(
            sha="", label=label, spawned_agent=agent, spawned_at=now,
            baseline_dirty=(), enabled=False,
        )

    async with _GIT_LOCK:
        try:
            _, sha, _ = await _git("rev-parse", "HEAD")
        except RuntimeError as exc:
            _log.warning("git_safety: snapshot HEAD rev-parse failed ({}). Checkpoint disabled for this run.", exc)
            return CheckpointHandle(
                sha="", label=label, spawned_agent=agent, spawned_at=now,
                baseline_dirty=(), enabled=False,
            )
        try:
            _, porcelain, _ = await _git("status", "--porcelain")
            baseline = tuple(sorted(_parse_porcelain(porcelain)))
        except RuntimeError as exc:
            _log.warning("git_safety: snapshot status read failed ({}). Disabling checkpoint.", exc)
            return CheckpointHandle(
                sha="", label=label, spawned_agent=agent, spawned_at=now,
                baseline_dirty=(), enabled=False,
            )

        _log.bind(agent=agent, sha=sha[:12], baseline_n=len(baseline)).info(
            "git_safety: snapshot {} @ {} (baseline-dirty paths: {})",
            agent, sha[:12], len(baseline),
        )
        return CheckpointHandle(
            sha=sha, label=label, spawned_agent=agent, spawned_at=now,
            baseline_dirty=baseline, enabled=True,
        )


async def verify_no_corruption(handle: CheckpointHandle) -> tuple[bool, str]:
    """Post-task sanity check. Returns (ok, reason)."""
    if not handle.enabled or not handle.sha:
        return True, "disabled"

    # 1. Working tree readable
    try:
        await _git("status", "--porcelain")
    except RuntimeError as exc:
        return False, f"git status failed: {exc}"

    # 2. agent-settings.json valid JSON
    try:
        cfg_path = settings.project_root / "app" / "config" / "agent-settings.json"
        json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"agent-settings.json broken: {exc}"

    # 3. App still imports (optional)
    if settings.git_verify_smoke_test:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import app",
            cwd=str(settings.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "import app smoke test timed out after 15s"
        if proc.returncode != 0:
            err = stderr_b.decode("utf-8", errors="replace").strip()[:500]
            return False, f"import app failed: {err}"

    return True, "ok"


class UnsafeSharedCheckpoint(RuntimeError):
    """A shared worktree provides no evidence of exclusive edit ownership."""


async def commit_checkpoint(handle: CheckpointHandle, summary: str) -> Optional[str]:
    if not handle.enabled or not handle.sha:
        return None
    raise UnsafeSharedCheckpoint(
        "Automatic commit refused: checkpoint has no isolated workspace ownership. "
        "Existing staged changes and concurrent edits have been preserved."
    )


async def rollback_to(handle: CheckpointHandle, reason: str) -> bool:
    if not handle.enabled or not handle.sha:
        return False
    raise UnsafeSharedCheckpoint(
        "Automatic rollback refused: checkpoint has no isolated workspace ownership. "
        "Working files and checkpoint have been preserved for recovery."
    )


# ── Sidecar persistence (handle <-> agent dir) ───────────────────────────

def checkpoint_path(agent_name: str) -> Path:
    return settings.agents_dir / agent_name / "CHECKPOINT.json"


def write_checkpoint(agent_name: str, handle: CheckpointHandle) -> None:
    """Persist handle alongside the agent so WaitForAgentTool can recover it."""
    path = checkpoint_path(agent_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            archive = settings.project_root / "data" / "recovery" / agent_name
            archive.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            (archive / f"checkpoint-{stamp}.json").write_bytes(path.read_bytes())
        path.write_text(json.dumps(handle.to_dict()), encoding="utf-8")
    except OSError as exc:
        _log.warning("git_safety: failed to write {} ({})", path, exc)


def read_checkpoint(agent_name: str) -> Optional[CheckpointHandle]:
    path = checkpoint_path(agent_name)
    if not path.exists():
        return None
    try:
        return CheckpointHandle.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("git_safety: failed to read {} ({})", path, exc)
        return None


def clear_checkpoint(agent_name: str) -> None:
    path = checkpoint_path(agent_name)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ── CLI helpers ──────────────────────────────────────────────────────────

async def list_checkpoint_commits(limit: int = 50) -> list[dict]:
    """Return the latest `yapoc:`-prefixed commits with labels.

    Used by `yapoc git checkpoints`. Each entry: {sha, short_sha, ts, subject}.
    """
    prefix = settings.git_checkpoint_label_prefix
    try:
        _, out, _ = await _git(
            "log",
            f"--grep=^{prefix}:",
            "-E",
            f"--max-count={limit}",
            "--pretty=format:%H%x09%h%x09%ci%x09%s",
        )
    except RuntimeError as exc:
        _log.warning("git_safety: list checkpoints failed ({})", exc)
        return []
    rows: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        rows.append({
            "sha": parts[0],
            "short_sha": parts[1],
            "ts": parts[2],
            "subject": parts[3],
        })
    return rows


async def manual_revert(sha: str) -> tuple[bool, str]:
    """Manual rollback target for `yapoc git revert <sha>`. Resets HEAD to sha."""
    if not sha or len(sha) < 4:
        return False, "sha required (≥4 chars)"
    async with _GIT_LOCK:
        try:
            await _git("rev-parse", "--verify", sha)
        except RuntimeError as exc:
            return False, f"unknown sha: {exc}"
        try:
            await _git("reset", "--hard", sha)
            return True, f"HEAD now at {sha[:12]}"
        except RuntimeError as exc:
            return False, f"reset failed: {exc}"
