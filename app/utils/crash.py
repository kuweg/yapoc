"""Crash tracking and output capture utilities.

Provides helpers for:
- Writing structured crash reports to CRASH.MD / SERVER_CRASH.MD
- Daemon threads that watch subprocess exit and capture output
- Output log rotation when files grow too large
"""

import os
import threading
from datetime import datetime
from pathlib import Path

from app.config import settings


def count_crashes(crash_path: Path) -> int:
    """Count ``## Crash`` headers in a crash report file."""
    if not crash_path.exists():
        return 0
    try:
        text = crash_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return text.count("## Crash")


def write_crash_report(
    crash_path: Path,
    *,
    pid: int,
    exit_code: int,
    entity_name: str,
    restart_count: int = 0,
    traceback_str: str = "",
    last_output_lines: str = "",
) -> None:
    """Append a structured crash entry to a CRASH.MD file."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        f"## Crash [PID {pid}] at {now}",
        f"- entity: {entity_name}",
        f"- exit_code: {exit_code}",
        f"- restart_count: {restart_count}",
    ]
    if traceback_str:
        parts.append("")
        parts.append("### Traceback")
        parts.append("```")
        parts.append(traceback_str.rstrip())
        parts.append("```")
    if last_output_lines:
        parts.append("")
        parts.append("### Last Output")
        parts.append("```")
        parts.append(last_output_lines.rstrip())
        parts.append("```")
    parts.append("---")
    parts.append("")

    with open(crash_path, "a", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")


def rotate_output_log(output_path: Path, max_size_kb: int | None = None) -> None:
    """Truncate oldest half of an output log when it exceeds *max_size_kb*."""
    if max_size_kb is None:
        max_size_kb = settings.log_max_size_kb

    if not output_path.exists():
        return
    size = output_path.stat().st_size
    if size <= max_size_kb * 1024:
        return

    try:
        text = output_path.read_text(encoding="utf-8", errors="replace")
        # Keep the second half
        midpoint = len(text) // 2
        truncated = "[... log rotated ...]\n" + text[midpoint:]
        output_path.write_text(truncated, encoding="utf-8")
    except OSError:
        pass


def _read_tail(log_path: Path, n: int = 30) -> str:
    """Read last *n* lines from a log file."""
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def _write_session_footer(log_file, entity_name: str, exit_code: int) -> None:
    """Write a session footer line to an open log file handle or path."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer = f"\n--- {entity_name} exited (code {exit_code}) at {now} ---\n"
    try:
        if hasattr(log_file, "write"):
            log_file.write(footer)
            log_file.flush()
        else:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(footer)
    except OSError:
        pass


def server_exit_watcher(
    proc,
    log_path: Path,
    crash_path: Path,
) -> threading.Thread:
    """Start a daemon thread that waits for *proc* to exit.

    On non-zero exit, writes a session footer and crash report.
    Returns the thread (already started).
    """

    def _watch():
        exit_code = proc.wait()
        _write_session_footer(log_path, "server", exit_code)
        rotate_output_log(log_path)
        if exit_code != 0:
            last_output = _read_tail(log_path)
            restart_count = count_crashes(crash_path)
            write_crash_report(
                crash_path,
                pid=proc.pid,
                exit_code=exit_code,
                entity_name="server",
                restart_count=restart_count,
                last_output_lines=last_output,
            )

    t = threading.Thread(target=_watch, daemon=True, name="server-exit-watcher")
    t.start()
    return t


def agent_exit_watcher(
    proc,
    log_path: Path,
    crash_path: Path,
    agent_name: str,
    restart_count: int = 0,
) -> threading.Thread:
    """Start a daemon thread that waits for an agent *proc* to exit.

    On non-zero exit, writes crash report.
    Returns the thread (already started).
    """

    def _watch():
        exit_code = proc.wait()
        _write_session_footer(log_path, agent_name, exit_code)
        rotate_output_log(log_path)
        if exit_code != 0:
            last_output = _read_tail(log_path)
            write_crash_report(
                crash_path,
                pid=proc.pid,
                exit_code=exit_code,
                entity_name=agent_name,
                restart_count=restart_count,
                last_output_lines=last_output,
            )

    t = threading.Thread(target=_watch, daemon=True, name=f"{agent_name}-exit-watcher")
    t.start()
    return t
