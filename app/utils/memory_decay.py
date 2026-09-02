"""Memory decay utilities for YAPOC.

Provides helpers for archiving stale entries from per-agent ``MEMORY.MD``
logs.  Agent memory files are written by the memory system in the format::

    **3. [2026-05-01 09:30] Some logged event text ...

Each entry carries a leading ``[YYYY-MM-DD HH:MM]`` datestamp.  Entries older
than a configurable age threshold are appended to an archival file under
``data/memory_archive/`` so the live memory log can be trimmed without losing
history.

This module is a standalone helper: it imports only stdlib + loguru and does
not depend on anything under ``app/agents/base/``.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

# Entry format: **N. [YYYY-MM-DD HH:MM] <text>
_ENTRY_RE = re.compile(
    r"^\*\*?\s*(?:\d+\.)?\s*\["
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}(?::\d{2})?"
    r"\]\s*(?P<text>.*)$"
)

# Fallback matcher for entries whose leading datestamp doesn't parse cleanly
# (e.g. date is present but malformed).  These are kept (never archived).
_DATESTAMP_RE = re.compile(r"\[(\d{4})-(\d{2})-(\d{2})\s+\d{2}:\d{2}\]")

# Base directory for agent memory files.
MEMORY_ROOT = Path("app/memory/agents")

# Archive destination root.
ARCHIVE_ROOT = Path("data/memory_archive")


def _parse_entry(line: str) -> tuple[datetime | None, str]:
    """Return ``(datestamp | None, raw_line)`` for a memory entry line.

    If the ``[YYYY-MM-DD HH:MM]`` datestamp is present and parses cleanly the
    datestamp is returned.  If the datestamp is malformed (non-date leading
    marker) ``None`` is returned and the caller falls back to the
    'unknown — keep' rule.
    """
    m = _ENTRY_RE.match(line)
    if m:
        date_text = m.group("date")
        try:
            dt = datetime.strptime(date_text, "%Y-%m-%d")
            return dt, m.group("text")
        except ValueError:
            return None, m.group("text")
    return None, line.strip()


def archive_stale_memory(
    agent_name: str,
    max_age_days: int = 30,
    dry_run: bool = False,
) -> dict:
    """Archive memory entries older than *max_age_days* days.

    Reads ``app/memory/agents/<agent_name>/MEMORY.MD`` and partitions its
    entries into "archived" (old enough or unparseable → omitted from the
    kept set) and "kept" (recent enough).  When *dry_run* is ``False`` the
    stale entries are appended to ``data/memory_archive/<agent_name>.archive.md``
    and the live file is rewritten keeping only the recent entries.

    Parameters
    ----------
    agent_name:
        Name of the agent whose ``MEMORY.MD`` should be decayed.
    max_age_days:
        Entries older than this many days are archived.  Default ``30``.
    dry_run:
        When ``True``, perform no writes and only report what *would* be
        archived.  Default ``False``.

    Returns
    -------
    dict
        ``{"status": "ok" | "no_file", "agent", "total_entries",
        "archived", "kept", "archive_path", "dry_run"}``.
    """
    mem_file = MEMORY_ROOT / agent_name / "MEMORY.MD"

    if not mem_file.exists():
        logger.info("memory_decay: no MEMORY.MD for agent={} path={}", agent_name, mem_file)
        return {
            "status": "no_file",
            "agent": agent_name,
        }

    text = mem_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    cutoff = datetime.now() - timedelta(days=max_age_days)

    kept_blocks: list[str] = []
    archived_blocks: list[str] = []
    stale_dates: list[str] = []

    current_block: list[str] = []
    current_is_stale = False

    def flush() -> None:
        nonlocal current_block, current_is_stale
        if not current_block:
            return
        block_text = "\n".join(current_block)
        if current_is_stale:
            archived_blocks.append(block_text)
        else:
            kept_blocks.append(block_text)
        current_block = []
        current_is_stale = False

    for line in lines:
        if _ENTRY_RE.match(line) or _DATESTAMP_RE.search(line):
            # Start of a new entry — flush the previous block first.
            flush()
            dt, _ = _parse_entry(line)
            if dt is None:
                # Leading date present but unparseable → keep (unknown).
                current_is_stale = False
            else:
                is_stale = dt < cutoff
                current_is_stale = is_stale
                if is_stale:
                    stale_dates.append(dt.strftime("%Y-%m-%d %H:%M"))
            current_block.append(line)
        else:
            # Continuation line — sticks with the current block.
            if current_block:
                current_block.append(line)
            else:
                # Preamble / header / trailing blank lines.
                kept_blocks.append(line)

    flush()

    total_entries = len(archived_blocks) + len(kept_blocks)

    if dry_run:
        logger.info(
            "memory_decay: dry_run agent={} total={} archived={} kept={}",
            agent_name,
            total_entries,
            len(archived_blocks),
            len(kept_blocks),
        )
        return {
            "status": "ok",
            "agent": agent_name,
            "total_entries": total_entries,
            "archived": len(archived_blocks),
            "kept": len(kept_blocks),
            "archive_path": str(ARCHIVE_ROOT / f"{agent_name}.archive.md"),
            "dry_run": True,
            "stale_dates": stale_dates,
        }

    # Write the archive and rewrite the live file.
    archive_path = ARCHIVE_ROOT / f"{agent_name}.archive.md"
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    if archived_blocks:
        archive_entry = "\n\n".join(archived_blocks) + "\n"
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write(archive_entry)

    if kept_blocks:
        new_text = "\n".join(kept_blocks)
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        mem_file.write_text(new_text, encoding="utf-8")
    else:
        # Everything archived — leave an empty file (or clear it).
        mem_file.write_text("", encoding="utf-8")

    logger.info(
        "memory_decay: ok agent={} archived={} kept={} archive={}",
        agent_name,
        len(archived_blocks),
        len(kept_blocks),
        archive_path,
    )
    return {
        "status": "ok",
        "agent": agent_name,
        "total_entries": total_entries,
        "archived": len(archived_blocks),
        "kept": len(kept_blocks),
        "archive_path": str(archive_path),
        "dry_run": False,
    }


def main() -> None:
    """CLI entry point for memory decay."""
    parser = argparse.ArgumentParser(description="Archive stale memory entries.")
    parser.add_argument("--agent", required=True, help="Agent name (dir under app/memory/agents/).")
    parser.add_argument("--days", type=int, default=30, help="Max age in days (default: 30).")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't write.")
    args = parser.parse_args()

    result = archive_stale_memory(args.agent, max_age_days=args.days, dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
