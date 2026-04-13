"""Background indexer — reads new MEMORY.MD lines and embeds them into SQLite.

Designed to run as an APScheduler job alongside Doctor/ModelManager.
Each agent's MEMORY.MD is tracked via a checkpoint (last indexed line number).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger as _log

from app.config import settings
from app.utils.db import (
    delete_agent_source_entries,
    get_checkpoint,
    get_checkpoint_hash,
    init_schema,
    insert_memory_entry,
    set_checkpoint,
    set_checkpoint_hash,
)
from app.utils.embeddings import embed_batch

# Agents that should not be indexed (base is a module, not an agent)
_SKIP_DIRS = {"base", "__pycache__"}

# Minimum content length to index (skip near-empty lines)
_MIN_CONTENT_LEN = 20


def _parse_memory_line(line: str) -> tuple[str, str]:
    """Extract timestamp and content from a MEMORY.MD line.

    Format: [YYYY-MM-DD HH:MM] task: ... | result: ...
    Returns (timestamp, full_line_content).
    """
    m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*(.+)$", line.strip())
    if m:
        return m.group(1), m.group(2)
    return "", line.strip()


def index_agent_memory(agent_name: str, agent_dir: Path) -> int:
    """Index new MEMORY.MD lines for a single agent. Returns count of new entries."""
    memory_path = agent_dir / "MEMORY.MD"
    if not memory_path.exists():
        return 0

    lines = memory_path.read_text(encoding="utf-8").splitlines()
    checkpoint = get_checkpoint(agent_name, "MEMORY.MD")

    # Only process lines after the checkpoint
    new_lines = lines[checkpoint:]
    if not new_lines:
        return 0

    # Filter out empty/short lines
    entries: list[tuple[str, str, int]] = []  # (timestamp, content, original_index)
    for i, line in enumerate(new_lines):
        line = line.strip()
        if len(line) < _MIN_CONTENT_LEN:
            continue
        ts, content = _parse_memory_line(line)
        if not ts:
            ts = "unknown"
        entries.append((ts, content, checkpoint + i))

    if not entries:
        # Still advance checkpoint even if all lines were too short
        set_checkpoint(agent_name, "MEMORY.MD", len(lines))
        return 0

    # Batch embed all content
    texts = [content for _, content, _ in entries]
    try:
        embeddings = embed_batch(texts)
    except Exception as exc:
        _log.error("Embedding failed for agent {}: {}", agent_name, exc)
        return 0

    # Insert into DB
    count = 0
    for (ts, content, _idx), emb in zip(entries, embeddings):
        try:
            insert_memory_entry(
                agent=agent_name,
                source="MEMORY.MD",
                content=content,
                timestamp=ts,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert memory entry for {}: {}", agent_name, exc)

    # Update checkpoint to total lines processed
    set_checkpoint(agent_name, "MEMORY.MD", len(lines))
    _log.info("Indexed {} new memory entries for agent '{}'", count, agent_name)
    return count


def _split_notes_sections(content: str) -> list[str]:
    """Split NOTES.MD into sections by ## headers for granular embedding.

    Each ## section becomes one entry. If no headers, the whole file is one entry.
    Skips sections shorter than _MIN_CONTENT_LEN.
    """
    parts = re.split(r'\n(?=##+ )', content)
    sections = [p.strip() for p in parts if len(p.strip()) >= _MIN_CONTENT_LEN]
    return sections if sections else [content.strip()]


def index_agent_notes(agent_name: str, agent_dir: Path) -> int:
    """Index NOTES.MD for a single agent. Re-indexes when content changes.

    Uses a content hash to detect changes — only re-indexes when NOTES.MD
    has been modified. Deletes old entries and inserts fresh ones on change.
    Returns count of entries indexed (0 if unchanged or empty).
    """
    notes_path = agent_dir / "NOTES.MD"
    if not notes_path.exists():
        return 0

    content = notes_path.read_text(encoding="utf-8").strip()
    if not content:
        return 0

    content_hash = hashlib.md5(content.encode()).hexdigest()
    if get_checkpoint_hash(agent_name, "NOTES.MD") == content_hash:
        return 0  # unchanged

    # Delete stale entries before re-indexing
    deleted = delete_agent_source_entries(agent_name, "NOTES.MD")
    if deleted:
        _log.debug("Removed {} stale NOTES.MD entries for '{}'", deleted, agent_name)

    sections = _split_notes_sections(content)
    try:
        embeddings = embed_batch(sections)
    except Exception as exc:
        _log.error("Embedding failed for agent {} NOTES.MD: {}", agent_name, exc)
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0
    for section, emb in zip(sections, embeddings):
        try:
            insert_memory_entry(
                agent=agent_name,
                source="NOTES.MD",
                content=section,
                timestamp=now,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert notes entry for {}: {}", agent_name, exc)

    set_checkpoint_hash(agent_name, "NOTES.MD", content_hash)
    _log.info("Indexed {} sections from {}/NOTES.MD", count, agent_name)
    return count


def index_agent_learnings(agent_name: str, agent_dir: Path) -> int:
    """Index LEARNINGS.MD for a single agent. Same hash-based approach as NOTES.MD."""
    learnings_path = agent_dir / "LEARNINGS.MD"
    if not learnings_path.exists():
        return 0

    content = learnings_path.read_text(encoding="utf-8").strip()
    if not content:
        return 0

    content_hash = hashlib.md5(content.encode()).hexdigest()
    if get_checkpoint_hash(agent_name, "LEARNINGS.MD") == content_hash:
        return 0  # unchanged

    deleted = delete_agent_source_entries(agent_name, "LEARNINGS.MD")
    if deleted:
        _log.debug("Removed {} stale LEARNINGS.MD entries for '{}'", deleted, agent_name)

    sections = _split_notes_sections(content)
    try:
        embeddings = embed_batch(sections)
    except Exception as exc:
        _log.error("Embedding failed for agent {} LEARNINGS.MD: {}", agent_name, exc)
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0
    for section, emb in zip(sections, embeddings):
        try:
            insert_memory_entry(
                agent=agent_name,
                source="LEARNINGS.MD",
                content=section,
                timestamp=now,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert learnings entry for {}: {}", agent_name, exc)

    set_checkpoint_hash(agent_name, "LEARNINGS.MD", content_hash)
    _log.info("Indexed {} sections from {}/LEARNINGS.MD", count, agent_name)
    return count


def index_shared_knowledge() -> int:
    """Index the shared KNOWLEDGE.MD file. Same hash-based approach as NOTES.MD."""
    knowledge_path = settings.agents_dir / "shared" / "KNOWLEDGE.MD"
    if not knowledge_path.exists():
        return 0

    content = knowledge_path.read_text(encoding="utf-8").strip()
    if not content:
        return 0

    content_hash = hashlib.md5(content.encode()).hexdigest()
    if get_checkpoint_hash("shared", "KNOWLEDGE.MD") == content_hash:
        return 0  # unchanged

    deleted = delete_agent_source_entries("shared", "KNOWLEDGE.MD")
    if deleted:
        _log.debug("Removed {} stale KNOWLEDGE.MD entries", deleted)

    sections = _split_notes_sections(content)
    try:
        embeddings = embed_batch(sections)
    except Exception as exc:
        _log.error("Embedding failed for shared KNOWLEDGE.MD: {}", exc)
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0
    for section, emb in zip(sections, embeddings):
        try:
            insert_memory_entry(
                agent="shared",
                source="KNOWLEDGE.MD",
                content=section,
                timestamp=now,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert shared knowledge entry: {}", exc)

    set_checkpoint_hash("shared", "KNOWLEDGE.MD", content_hash)
    _log.info("Indexed {} sections from shared/KNOWLEDGE.MD", count)
    return count


def run_indexer() -> int:
    """Index all agents' MEMORY.MD, NOTES.MD, and LEARNINGS.MD files. Returns total entries indexed."""
    init_schema()
    total = 0

    agents_dir = settings.agents_dir
    if not agents_dir.exists():
        return 0

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name in _SKIP_DIRS:
            continue
        try:
            total += index_agent_memory(agent_dir.name, agent_dir)
            total += index_agent_notes(agent_dir.name, agent_dir)
            total += index_agent_learnings(agent_dir.name, agent_dir)
        except Exception as exc:
            _log.error("Indexer error for agent '{}': {}", agent_dir.name, exc)

    # Index shared knowledge base
    try:
        total += index_shared_knowledge()
    except Exception as exc:
        _log.error("Indexer error for shared knowledge: {}", exc)

    return total
