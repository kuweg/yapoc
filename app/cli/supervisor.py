"""External supervisor — keeps uvicorn alive across crashes.

``yapoc start`` spawns uvicorn and then returns; if uvicorn dies later
(unhandled exception, OOM, SIGKILL from a misbehaving sub-agent), YAPOC
stays dead until someone notices and runs ``yapoc start`` again. This
module provides ``yapoc supervise`` — a foreground loop that owns the
uvicorn child, watches it, and respawns it on crash with exponential
backoff. Run it under your favourite OS-level supervisor (systemd,
launchd, nohup, screen, tmux) and YAPOC survives overnight.

Why not systemd directly?
  - YAPOC ships as a single-repo Python app installed via Poetry. A
    pure-Python supervisor keeps everything in-repo and works on any OS
    Poetry runs on. The user can still wrap THIS process in systemd if
    they want a second tier of supervision; it composes cleanly.

Crash semantics:
  - exit code != 0 (or != 0 even if we asked for shutdown — see graceful
    flag below) is a crash; record it to SUPERVISOR.MD and restart with
    backoff.
  - "Fast crash" = died within ``alive_threshold_s`` seconds of being
    spawned. After ``circuit_break_after_n`` consecutive fast crashes,
    pause for ``circuit_break_seconds`` to avoid a tight crash-respawn
    loop that pegs the CPU.
  - Successful uptime past the threshold resets the consecutive-fast-
    crash counter.

Graceful shutdown:
  - SIGINT / SIGTERM to the supervisor → forward to uvicorn → wait
    grace_seconds for it to exit → SIGKILL if it doesn't. Exit cleanly
    without recording a crash.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger as _log

from app.config import settings


_SUPERVISOR_PID_FILE = Path(".yapoc.supervisor.pid")
_SUPERVISOR_LOG = settings.agents_dir / "master" / "SUPERVISOR.MD"
_UVICORN_OUTPUT = settings.agents_dir / "master" / "SERVER_OUTPUT.MD"


def _write_pid(path: Path, pid: int) -> None:
    try:
        path.write_text(str(pid))
    except OSError:
        pass


def _clear_pid(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_event(line: str) -> None:
    """Append a single line to SUPERVISOR.MD. Best-effort."""
    try:
        _SUPERVISOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_SUPERVISOR_LOG, "a", encoding="utf-8") as f:
            f.write(line if line.endswith("\n") else line + "\n")
    except OSError:
        pass


def _backoff_seconds(consecutive_fast: int, max_backoff: int) -> float:
    """Exponential backoff: 1s, 2s, 4s, 8s … capped at ``max_backoff``."""
    if consecutive_fast <= 0:
        return 1.0
    return float(min(max_backoff, 1 << min(consecutive_fast, 8)))


def _last_log_lines(path: Path, n: int = 5) -> list[str]:
    """Return the last ``n`` non-blank lines from a log file (best-effort)."""
    try:
        with open(path, "rb") as f:
            try:
                f.seek(-8192, os.SEEK_END)
            except OSError:
                f.seek(0)
            tail = f.read().decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
        return lines[-n:]
    except OSError:
        return []


def supervise(host: str | None = None, port: int | None = None) -> int:
    """Run the supervisor in the foreground. Returns the exit code.

    The single-instance check is via ``.yapoc.supervisor.pid`` —
    starting a second supervisor against the same project is refused
    so we don't end up with two parents fighting over a uvicorn child.
    """
    host = host or settings.host
    port = port or settings.port

    # Refuse to start if another supervisor is already running.
    if _SUPERVISOR_PID_FILE.exists():
        try:
            prior_pid = int(_SUPERVISOR_PID_FILE.read_text().strip())
            try:
                os.kill(prior_pid, 0)
                _log.error(
                    "Supervisor already running (PID {}). Stop it first or "
                    "remove {} if it's stale.",
                    prior_pid, _SUPERVISOR_PID_FILE,
                )
                return 2
            except ProcessLookupError:
                _clear_pid(_SUPERVISOR_PID_FILE)
        except (ValueError, OSError):
            _clear_pid(_SUPERVISOR_PID_FILE)

    _write_pid(_SUPERVISOR_PID_FILE, os.getpid())
    _log_event(f"[{_ts()}] SUPERVISOR START — pid={os.getpid()} host={host} port={port}")
    _log.info("Supervisor starting (pid {}) — uvicorn on {}:{}", os.getpid(), host, port)

    # Tunables — all live in app/config/settings.py so they're discoverable
    # alongside the rest of the runtime configuration.
    alive_threshold_s = float(getattr(settings, "supervisor_alive_threshold_s", 60.0))
    max_backoff_s = int(getattr(settings, "supervisor_max_backoff_s", 30))
    circuit_break_after_n = int(getattr(settings, "supervisor_circuit_break_after_n", 5))
    circuit_break_s = int(getattr(settings, "supervisor_circuit_break_seconds", 300))
    grace_s = float(getattr(settings, "supervisor_grace_seconds", 10.0))

    # State across respawns.
    consecutive_fast_crashes = 0
    shutdown_requested = False
    proc: subprocess.Popen[bytes] | None = None

    def _request_shutdown(signum: int, _frame) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True
        _log.info("Supervisor received signal {} — initiating graceful shutdown", signum)
        _log_event(f"[{_ts()}] SUPERVISOR SHUTDOWN REQUESTED — signal={signum}")
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        while not shutdown_requested:
            _UVICORN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(_UVICORN_OUTPUT, "a", encoding="utf-8")
            spawned_at = time.monotonic()
            try:
                proc = subprocess.Popen(
                    [
                        sys.executable, "-m", "uvicorn", "app.backend.main:app",
                        "--host", host, "--port", str(port),
                    ],
                    stdout=log_fh,
                    stderr=log_fh,
                )
            except OSError as exc:
                _log.error("Supervisor: spawn failed ({}). Sleeping 5s.", exc)
                _log_event(f"[{_ts()}] SPAWN FAILED — {exc}")
                log_fh.close()
                time.sleep(5)
                continue

            _log_event(
                f"[{_ts()}] SPAWN — pid={proc.pid} consecutive_fast_crashes={consecutive_fast_crashes}"
            )
            _log.info("Supervisor spawned uvicorn (PID {})", proc.pid)

            # Block until child exits OR shutdown was requested.
            try:
                exit_code = proc.wait()
            except KeyboardInterrupt:
                # Bubble up so the signal handler's flag is honored.
                _request_shutdown(signal.SIGINT, None)
                exit_code = proc.wait() if proc else -1

            log_fh.close()
            alive_s = time.monotonic() - spawned_at

            if shutdown_requested:
                _log_event(
                    f"[{_ts()}] GRACEFUL EXIT — uvicorn pid={proc.pid if proc else '?'} "
                    f"exit={exit_code} alive={alive_s:.1f}s"
                )
                # Force-kill if it didn't honor SIGTERM in time.
                if proc and proc.poll() is None:
                    time.sleep(grace_s)
                    if proc.poll() is None:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                break

            # Treat any unexpected exit as a crash, even exit_code==0 — the
            # backend is expected to run indefinitely until we ask it to stop.
            tail = _last_log_lines(_UVICORN_OUTPUT, n=5)
            tail_preview = " | ".join(tail)[:400] if tail else "(no recent log lines)"
            _log_event(
                f"[{_ts()}] CRASH — exit={exit_code} alive={alive_s:.1f}s tail={tail_preview!r}"
            )
            _log.warning(
                "uvicorn exited (code={} alive={:.1f}s). Restarting.",
                exit_code, alive_s,
            )

            if alive_s < alive_threshold_s:
                consecutive_fast_crashes += 1
            else:
                # The process ran long enough to be considered healthy;
                # reset the counter even though it eventually died.
                consecutive_fast_crashes = 0

            if consecutive_fast_crashes >= circuit_break_after_n:
                _log_event(
                    f"[{_ts()}] CIRCUIT BREAK — {consecutive_fast_crashes} fast crashes; "
                    f"sleeping {circuit_break_s}s"
                )
                _log.error(
                    "Circuit break: {} fast crashes. Pausing {}s to avoid a tight loop.",
                    consecutive_fast_crashes, circuit_break_s,
                )
                # Sleep in 5s slices so SIGINT/SIGTERM still interrupts.
                slept = 0
                while slept < circuit_break_s and not shutdown_requested:
                    time.sleep(min(5, circuit_break_s - slept))
                    slept += 5
                consecutive_fast_crashes = 0
                continue

            delay = _backoff_seconds(consecutive_fast_crashes, max_backoff_s)
            _log_event(f"[{_ts()}] BACKOFF — sleeping {delay:.1f}s before respawn")
            slept = 0.0
            while slept < delay and not shutdown_requested:
                time.sleep(min(1.0, delay - slept))
                slept += 1.0

        _log_event(f"[{_ts()}] SUPERVISOR EXIT — graceful")
        return 0
    finally:
        _clear_pid(_SUPERVISOR_PID_FILE)
