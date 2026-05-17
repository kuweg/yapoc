"""Git autocheckpoint helpers — snapshot before sub-agent task, verify
on terminal status, commit-or-rollback based on the result.

Granularity is per-sub-agent-task (see plan: surgical v1). Wired into
``SpawnAgentTool`` (snapshot) and ``WaitForAgentTool`` / ``WaitForAgentsTool``
(verify+commit/rollback). Disabled in lockstep when
``settings.git_autocheckpoint_enabled`` is False — every helper returns
a no-op handle so caller paths stay uniform.

The lock serializes git ops across parallel agent spawns.
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

    Net-new paths the agent touches afterwards are what commit/rollback act on.
    Paths the user had dirty at snapshot time are explicitly left alone.

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


async def commit_checkpoint(handle: CheckpointHandle, summary: str) -> Optional[str]:
    """Verify passed → commit ONLY the paths the agent newly touched.

    Paths that were already dirty at snapshot time (``handle.baseline_dirty``)
    are explicitly excluded — they're the user's. Returns the new commit SHA,
    or None if the agent produced no net-new changes (no commit needed).
    """
    if not handle.enabled or not handle.sha:
        return None

    async with _GIT_LOCK:
        try:
            _, porcelain, _ = await _git("status", "--porcelain")
        except RuntimeError as exc:
            _log.warning("git_safety: commit status check failed ({}). Skipping commit.", exc)
            return None

        current = _parse_porcelain(porcelain)
        baseline = set(handle.baseline_dirty)
        agent_paths = sorted(current - baseline)
        if not agent_paths:
            _log.bind(agent=handle.spawned_agent).debug(
                "git_safety: no agent-touched paths for {}", handle.spawned_agent
            )
            return None

        clean_summary = summary.replace("\n", " ").strip()[:60]
        msg = f"{settings.git_checkpoint_label_prefix}:agent:{handle.spawned_agent}:done — {clean_summary}"
        try:
            # Stage only paths the agent introduced/modified.
            await _git("add", "--", *agent_paths)
            await _git("commit", "-m", msg, "--no-verify")
            _, new_sha, _ = await _git("rev-parse", "HEAD")
            _log.bind(agent=handle.spawned_agent, sha=new_sha[:12], n_paths=len(agent_paths)).info(
                "git_safety: checkpoint commit {} for {} ({} paths)",
                new_sha[:12], handle.spawned_agent, len(agent_paths),
            )
            return new_sha
        except RuntimeError as exc:
            _log.warning("git_safety: commit failed ({}). Working tree left as-is.", exc)
            return None


async def rollback_to(handle: CheckpointHandle, reason: str) -> bool:
    """Verify failed → revert ONLY the agent-touched paths to handle.sha state.

    Paths in ``baseline_dirty`` are left untouched (user's). Returns True if
    any rollback action ran, False if disabled. Best-effort: logs and continues
    on any individual step failure rather than raising.
    """
    if not handle.enabled or not handle.sha:
        return False

    async with _GIT_LOCK:
        try:
            _, porcelain, _ = await _git("status", "--porcelain")
        except RuntimeError as exc:
            _log.error("git_safety: rollback status read failed ({}). Tree not modified.", exc)
            return False

        current = _parse_porcelain(porcelain)
        baseline = set(handle.baseline_dirty)
        agent_paths = sorted(current - baseline)

        import shutil
        for path in agent_paths:
            # Untracked dirs come through as "agent_dir/" with trailing slash.
            cleaned = path.rstrip("/")
            full = settings.project_root / cleaned
            try:
                # Was this path tracked at handle.sha? `cat-file -e` returns 0
                # when the object exists at that ref. If yes → restore via
                # checkout; if no → the agent created it, remove it.
                rc, _, _ = await _git(
                    "cat-file", "-e", f"{handle.sha}:{cleaned}", check=False,
                )
                if rc == 0:
                    await _git("checkout", handle.sha, "--", cleaned)
                else:
                    if full.is_symlink() or full.is_file():
                        try:
                            full.unlink()
                        except OSError as exc:
                            _log.warning("git_safety: failed to unlink {} ({})", full, exc)
                    elif full.is_dir():
                        try:
                            shutil.rmtree(full)
                        except OSError as exc:
                            _log.warning("git_safety: failed to rmtree {} ({})", full, exc)
            except RuntimeError as exc:
                _log.warning("git_safety: rollback step for {} failed ({})", path, exc)

        # Audit to master HEALTH.MD
        try:
            health_path = settings.agents_dir / "master" / "HEALTH.MD"
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            line = (
                f"[{ts}] ROLLBACK: agent={handle.spawned_agent} sha={handle.sha[:12]} "
                f"paths={len(agent_paths)} label={handle.label!r} reason={reason!r}\n"
            )
            health_path.parent.mkdir(parents=True, exist_ok=True)
            with health_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            _log.warning("git_safety: HEALTH.MD audit append failed ({})", exc)

        _log.bind(agent=handle.spawned_agent, sha=handle.sha[:12], n=len(agent_paths), reason=reason).warning(
            "git_safety: ROLLBACK {} paths for {} (sha={}) — {}",
            len(agent_paths), handle.spawned_agent, handle.sha[:12], reason,
        )
        return True


# ── Sidecar persistence (handle <-> agent dir) ───────────────────────────

def checkpoint_path(agent_name: str) -> Path:
    return settings.agents_dir / agent_name / "CHECKPOINT.json"


def write_checkpoint(agent_name: str, handle: CheckpointHandle) -> None:
    """Persist handle alongside the agent so WaitForAgentTool can recover it."""
    path = checkpoint_path(agent_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
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
