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


def _extract_task_and_result(task_path: Path) -> str | None:
    """Extract the ## Task + ## Result sections from a TASK.MD file for indexing.

    Returns combined content or None if the task is not in a terminal state.
    """
    if not task_path.exists():
        return None
    content = task_path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    # Only index tasks that are done or error (not pending/running)
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if line.startswith("status:") and "done" not in line and "error" not in line:
                return None

    task_section = ""
    result_section = ""
    m = re.search(r"## Task\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        task_section = m.group(1).strip()
    m = re.search(r"## Result\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        result_section = m.group(1).strip()

    combined = f"Task: {task_section}\nResult: {result_section}"
    if len(combined.strip()) < _MIN_CONTENT_LEN:
        return None
    return combined


def index_agent_tasks(agent_name: str, agent_dir: Path) -> int:
    """Index completed TASK.MD results for semantic search of past work.

    Only indexes tasks that are done or error (not pending/running).
    Uses hash-based change detection like NOTES.MD.
    """
    task_path = agent_dir / "TASK.MD"
    if not task_path.exists():
        return 0

    content = task_path.read_text(encoding="utf-8").strip()
    if not content:
        return 0

    content_hash = hashlib.md5(content.encode()).hexdigest()
    if get_checkpoint_hash(agent_name, "TASK.MD") == content_hash:
        return 0

    deleted = delete_agent_source_entries(agent_name, "TASK.MD")
    if deleted:
        _log.debug("Removed {} stale TASK.MD entries for '{}'", deleted, agent_name)

    entry_text = _extract_task_and_result(task_path)
    if not entry_text:
        set_checkpoint_hash(agent_name, "TASK.MD", content_hash)
        return 0

    try:
        embeddings = embed_batch([entry_text])
    except Exception as exc:
        _log.error("Embedding failed for agent {} TASK.MD: {}", agent_name, exc)
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        insert_memory_entry(
            agent=agent_name,
            source="TASK.MD",
            content=entry_text,
            timestamp=now,
            embedding=embeddings[0],
        )
    except Exception as exc:
        _log.warning("Failed to insert task entry for {}: {}", agent_name, exc)
        return 0

    set_checkpoint_hash(agent_name, "TASK.MD", content_hash)
    _log.info("Indexed TASK.MD result for agent '{}'", agent_name)
    return 1


_REPORT_HEADER_RE = re.compile(
    r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+—\s+Self-evaluation",
    re.MULTILINE,
)


def index_agent_report(agent_name: str, agent_dir: Path) -> int:
    """Index REPORT.MD per round section, deduped by content hash.

    Unlike NOTES.MD/LEARNINGS.MD (which delete-and-reindex on file-hash
    change), REPORT.MD is an append-only log of rounds. We want to
    accumulate entries across runs, not replace them. The scheme:

      1. Split REPORT.MD by ``## YYYY-MM-DD HH:MM — Self-evaluation`` headers
      2. For each section, hash its content (MD5)
      3. Look up existing memory_entries with source=REPORT.MD for this
         agent and build the set of hashes already stored
      4. Embed + insert only sections whose hash isn't in that set

    This lets the evaluator overwrite REPORT.MD freely (keeping only the
    most recent N rounds for human readability); older rounds remain
    durably indexed in the vector store and reachable via search_memory.
    Returns the number of NEW sections indexed.
    """
    report_path = agent_dir / "REPORT.MD"
    if not report_path.exists():
        return 0

    content = report_path.read_text(encoding="utf-8").strip()
    if not content:
        return 0

    matches = list(_REPORT_HEADER_RE.finditer(content))
    if not matches:
        return 0

    sections: list[tuple[str, str]] = []  # (timestamp, section_text)
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_text = content[start:end].strip()
        if len(section_text) < _MIN_CONTENT_LEN:
            continue
        sections.append((m.group(1), section_text))

    if not sections:
        return 0

    # Build the set of already-indexed section hashes for this agent
    from app.utils.db import get_db
    db = get_db()
    rows = db.execute(
        "SELECT content FROM memory_entries WHERE agent = ? AND source = ?",
        (agent_name, "REPORT.MD"),
    ).fetchall()
    seen = {hashlib.md5(r["content"].encode()).hexdigest() for r in rows}

    to_index: list[tuple[str, str]] = []
    for ts, section_text in sections:
        h = hashlib.md5(section_text.encode()).hexdigest()
        if h not in seen:
            to_index.append((ts, section_text))

    if not to_index:
        return 0

    try:
        embeddings = embed_batch([s for _, s in to_index])
    except Exception as exc:
        _log.error("Embedding failed for agent {} REPORT.MD: {}", agent_name, exc)
        return 0

    count = 0
    for (ts, section_text), emb in zip(to_index, embeddings):
        try:
            insert_memory_entry(
                agent=agent_name,
                source="REPORT.MD",
                content=section_text,
                timestamp=ts,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert REPORT.MD section for {}: {}", agent_name, exc)

    if count:
        _log.info("Indexed {} new REPORT.MD section(s) for agent '{}'", count, agent_name)
    return count


def run_indexer() -> int:
    """Index all agents' MEMORY.MD, NOTES.MD, LEARNINGS.MD, TASK.MD, and
    REPORT.MD files plus shared/KNOWLEDGE.MD. Returns total entries indexed."""
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
            total += index_agent_tasks(agent_dir.name, agent_dir)
            total += index_agent_report(agent_dir.name, agent_dir)
        except Exception as exc:
            _log.error("Indexer error for agent '{}': {}", agent_dir.name, exc)

    # Index shared knowledge base
    try:
        total += index_shared_knowledge()
    except Exception as exc:
        _log.error("Indexer error for shared knowledge: {}", exc)

    return total
