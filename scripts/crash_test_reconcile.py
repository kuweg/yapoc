"""Crash-test harness for the stale git-checkpoint reconcile.

Simulates the exact on-disk state a backend crash mid-task leaves behind,
then drives the REAL reconcile code path end-to-end in a throwaway git repo
so the live project tree is never touched and the security gate is not
provoked.

Test theory (mirrors production crash gap):
  A. baseline committed            -> workfile.txt = "v1"
  B. snapshot_state("builder")     -> persists CHECKPOINT.json @ baseline sha
                                       (as delegation.py does pre-spawn)
  C. agent mutation                -> workfile.txt becomes garbage (half-applied)
                                       but agent never reaches terminal status
                                       (the "crash"), so CHECKPOINT.json stays
  D. reconcile_stale_checkpoints(["builder"])   (the startup recovery path)
  E. assert rollback: workfile.txt back to "v1", CHECKPOINT.json gone,
     master/HEALTH.MD has ROLLBACK audit line, returned == ["builder"]

Everything is monkeypatched through app.config.settings so project_root and
agents_dir point at the throwaway repo. All real git operations run there.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 1. Build a throwaway git repo resembling the project ──────────────────
REPO = Path(tempfile.mkdtemp(prefix="yapoc_crash_test_"))
AGENTS = REPO / "app" / "agents"
WORKFILE = REPO / "workfile.txt"

AGENT = "builder"       # simulated crash victim (exercises a real name)
CHECKPOINT_FILE = AGENTS / AGENT / "CHECKPOINT.json"
HEALTH_FILE = AGENTS / "master" / "HEALTH.MD"

def git(*args, cwd: str | None = None) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd or str(REPO),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} rc={r.returncode}: {r.stderr}")
    return r.stdout.strip()

def fresh_baseline() -> str:
    git("init", "-q")
    git("config", "user.email", "test@local")
    git("config", "user.name", "crash test")
    AGENTS.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text("", encoding="utf-8")
    WORKFILE.write_text("v1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "baseline")
    return git("rev-parse", "HEAD")


def main() -> None:
    baseline_sha = fresh_baseline()

    # 2. Monkeypatch so the real code paths target the throwaway repo.
    # git_safety and git_checkpoint_reconcile both did `from app.config
    # import settings`, so we must rebind the attribute on EACH module that
    # holds a direct reference. project_root/agents_dir are read-only
    # properties on the real Settings, so we use a lightweight stand-in that
    # exposes exactly the attributes the reconcile/rollback code paths read.
    class _FakeSettings:
        pass

    fake = _FakeSettings()
    fake.project_root = REPO
    fake.agents_dir = AGENTS
    fake.git_autocheckpoint_enabled = True
    fake.git_verify_smoke_test = False      # skip import-app smoke in _git? n/a
    fake.git_checkpoint_label_prefix = "yapoc"

    import app.backend.git_safety as gs
    import app.backend.git_checkpoint_reconcile as rec
    restored = [
        gs.settings,      # original bindings to restore in finally
        rec.settings,
    ]
    gs.settings = fake
    rec.settings = fake

    async def run() -> bool:
        # B. snapshot the pre-task baseline as delegation.py would.
        handle = await gs.snapshot_state("master->builder:crash-test", AGENT)
        print(f"[B] snapshot enabled={handle.enabled} sha={handle.sha[:12]!s} "
              f"(expect {baseline_sha[:12]}) @ {REPO}")
        gs.write_checkpoint(AGENT, handle)
        cp = CHECKPOINT_FILE.read_text(encoding="utf-8")
        print(f"[B] CHECKPOINT.json persisted: {json.loads(cp)['enabled']} "
              f"sha={json.loads(cp)['sha'][:12]}")
        assert handle.enabled, "snapshot should be enabled under fake settings"
        assert handle.sha == baseline_sha

        # C. The agent mutates the working tree, then CRASHES before terminal.
        WORKFILE.write_text("v2 + PARTIAL GARBAGE WRITTEN MID-MUTATION\n",
                            encoding="utf-8")
        print(f"[C] agent mutated workfile -> {WORKFILE.read_text()!r}")
        # crash => CHECKPOINT.json left on disk unresolved (we do NOT finalize)

        # D. Startup recovery. builder is deemed stale; reconcile runs.
        reconciled = await rec.reconcile_stale_checkpoints([AGENT])
        print(f"[D] reconcile returned {reconciled}")

        # E. Assertions
        ok = True
        def check(label: str, cond: bool) -> None:
            nonlocal ok
            print(f"    [{'PASS' if cond else 'FAIL'}] {label}")
            if not cond:
                ok = False

        check("workfile rolled back to baseline", WORKFILE.read_text() == "v1\n")
        check("CHECKPOINT.json cleared", not CHECKPOINT_FILE.exists())
        check("returned the stale agent", reconciled == [AGENT])
        health = HEALTH_FILE.read_text(encoding="utf-8")
        check("HEALTH.MD audit written", "ROLLBACK" in health
              and AGENT in health and baseline_sha[:12] in health)
        if health:
            print("    health audit line:", health.strip().splitlines()[-1][:120])
        # The audit append writes to app/agents/master/HEALTH.MD — that path
        # legitimately ends up dirty (it IS the rollback record). So the tree
        # is not byte-identical to baseline; the ONLY expected remaining diff
        # is that audit file. Any other dirty path = a failed rollback.
        porcelain = git("status", "--porcelain")
        # The audit append can surface as staged (`M `) or unstaged (` M`),
        # depending on what the rollback checkout touched. Robustly extract
        # each path (strip the XY status prefix whatever its position) and
        # compare against the expected sole-audit-file remaining diff.
        dirty_paths = set()
        for ln in porcelain.splitlines():
            if not ln:
                continue
            candidate = ln
            # drop leading status columns: both X and Y up to first path char
            p = candidate.strip()                 # trim edge whitespace
            # porcelain status columns sit in indices 0..2 (`XY `). After a
            # `.strip()` a staged line 'M app/...' still has XY glued, so find
            # the path by locating the run after two status chars / separator.
            parts = candidate.split(" ", 1)
            p = parts[-1].strip() if len(parts) > 1 else candidate
            if " -> " in p:
                p = p.split(" -> ", 1)[1]
            dirty_paths.add(p)
        audit_only = dirty_paths == {"app/agents/master/HEALTH.MD"}
        check("no stray agent mutations remain (only audit HEALTH.MD differs)",
              audit_only)
        if dirty_paths != {"app/agents/master/HEALTH.MD"}:
            print(f"    unexpected diff paths: {dirty_paths!r}")
            print("    RAW porcelain lines:", [repr(x) for x in porcelain.splitlines()])
        return ok

    try:
        passed = asyncio.run(run())
    finally:
        gs.settings, rec.settings = restored   # restore real bindings
        shutil.rmtree(REPO, ignore_errors=True)

        status = "PASS" if passed else "FAIL"
        print(f"\n=== RESULT: {status} (throwaway repo {REPO} cleaned up) ===")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
