"""Conversation snapshot storage for YAPOC.

Provides helpers for persisting rendered transcripts of chat sessions and
listing available snapshots.  Each snapshot is stored as a single markdown
file under ``data/conversations/<session_id>.md`` using an atomic
write-then-replace so readers never observe partially-written files.

This module is a standalone helper: it imports only stdlib + loguru and does
not depend on anything under ``app/agents/base/``.
"""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

from loguru import logger

# Valid session ids: letters, digits, underscore, hyphen.
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Base directory for conversation snapshots.
# Absolute: agents run as subprocesses whose CWD is not the repo root, and a
# relative path there writes snapshots somewhere nobody reads them back from.
from app.config import settings as _settings
CONVERSATION_ROOT = _settings.project_root / "data" / "conversations"


def _validate_session_id(session_id: str) -> str:
    """Return the session id if valid, else raise ``ValueError``."""
    if not isinstance(session_id, str) or not _SESSION_RE.match(session_id):
        raise ValueError(
            f"Invalid session_id {session_id!r}: must match {_SESSION_RE.pattern!r}"
        )
    return session_id


def snapshot(session_id: str, transcript_md: str) -> Path:
    """Persist a transcript as an atomic snapshot for *session_id*.

    Parameters
    ----------
    session_id:
        Identifier for the conversation.  Must match ``^[A-Za-z0-9_-]+$`` or a
        ``ValueError`` is raised.
    transcript_md:
        Markdown body of the transcript to store.

    Returns
    -------
    Path
        The path of the written snapshot file.
    """
    sid = _validate_session_id(session_id)

    CONVERSATION_ROOT.mkdir(parents=True, exist_ok=True)
    target = CONVERSATION_ROOT / f"{sid}.md"

    # Atomic write: write to a temp file in the same directory, fsync, then
    # os.replace onto the final path so no partial reads can occur.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(CONVERSATION_ROOT),
        prefix=f".{sid}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(transcript_md)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        # Best-effort cleanup of the temp file on any failure.
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    logger.info("conversation_store: snapshot written id={} path={}", sid, target)
    return target


def load(session_id: str) -> str | None:
    """Return the transcript for *session_id* or ``None`` if not found.

    Invalid session identifiers (not matching the safe allowed set) return
    ``None`` rather than raising.
    """
    sid = _validate_session_id(session_id)
    target = CONVERSATION_ROOT / f"{sid}.md"
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def list_snapshots() -> list[str]:
    """Return a sorted list of snapshot ids found under the store.

    Only ``*.md`` files whose basename (without extension) matches the safe
    session-id charset are returned.
    """
    if not CONVERSATION_ROOT.is_dir():
        return []
    ids: list[str] = []
    for child in CONVERSATION_ROOT.iterdir():
        if not child.is_file() or child.suffix != ".md":
            continue
        name = child.name[: -len(".md")]
        if _SESSION_RE.match(name):
            ids.append(name)
    return sorted(ids)


def main() -> None:
    """CLI entry point for conversation store operations."""
    parser = argparse.ArgumentParser(description="Conversation snapshot store.")
    parser.add_argument("--snapshot", help="Session id to snapshot or load.")
    parser.add_argument("--transcript", help="Path to a transcript .md file to store (with --snapshot).")
    parser.add_argument("--list", action="store_true", help="List all snapshot ids.")
    args = parser.parse_args()

    if args.list:
        for sid in list_snapshots():
            print(sid)
        return

    if args.snapshot:
        sid = args.snapshot
        if args.transcript:
            payload = Path(args.transcript).read_text(encoding="utf-8")
            path = snapshot(sid, payload)
            print(path)
        else:
            content = load(sid)
            if content is None:
                print(f"NOT_FOUND: {sid}")
            else:
                print(content)
        return

    # No arguments — just print usage.
    parser.print_help()


if __name__ == "__main__":
    main()
