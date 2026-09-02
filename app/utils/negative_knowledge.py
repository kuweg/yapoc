"""Negative knowledge helpers for YAPOC.

Loads, searches, and renders entries from ``app/agents/shared/NEGATIVE_KNOWLEDGE.md``.
Negative knowledge captures recorded pitfalls, anti-patterns, and lessons
learned so future agents can avoid repeating mistakes.

Two entry conventions are supported — see :func:`load_entries`:

    ## <title>
    - status: rejected | failed | obsolete | superseded
    - decision: <what was tried>
    - why: <why it was rejected>

...and the older one-line form ``- **<topic>**: <lesson>``.

This module is a standalone helper and does not depend on anything under
``app/agents/base/``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from loguru import logger

from app.config import settings

# Path to the shared negative-knowledge document. Absolute: sub-agents run as
# subprocesses whose CWD is not guaranteed to be the repo root, and a relative
# path there silently yields an empty store.
KNOWLEDGE_FILE = settings.project_root / "app" / "agents" / "shared" / "NEGATIVE_KNOWLEDGE.md"

# Legacy one-line form: - **topic**: <lesson>
_ENTRY_RE = re.compile(r"^\s*-\s+\*\*(?P<topic>[^*]+)\*\*\s*:\s*(?P<lesson>.+)$")
# Field inside a `## heading` block: - key: value
_FIELD_RE = re.compile(r"^\s*-\s+(?P<key>status|decision|why|by|date)\s*:\s*(?P<value>.+)$", re.I)


def load_entries() -> list[dict]:
    """Parse negative-knowledge entries from the shared file.

    Two shapes are accepted, because the writer and the reader disagreed:

    1. ``## <title>`` heading followed by ``- status/decision/why/by/date``
       lines — what the librarian actually writes and what the seed entries
       use. The previous parser skipped every ``##`` line, so a file with five
       entries loaded as zero.
    2. ``- **topic**: <lesson>`` one-liners — the original convention, kept so
       older notes still load.

    Returns ``{"topic", "lesson", ...}`` dicts in document order; block entries
    additionally carry ``status``, ``decision``, ``why``, ``by`` and ``date``.
    """
    entries: list[dict] = []

    if not KNOWLEDGE_FILE.exists():
        logger.warning("negative_knowledge: file not found path={}", KNOWLEDGE_FILE)
        return entries

    text = KNOWLEDGE_FILE.read_text(encoding="utf-8", errors="replace")

    # Strip HTML comments so the format documentation in the header (which
    # contains an example entry) is not parsed as real entries.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            if current:
                entries.append(current)
            current = {"topic": stripped[3:].strip(), "lesson": ""}
            continue
        # A top-level `# ` title ends any open block without starting one.
        if stripped.startswith("# "):
            if current:
                entries.append(current)
            current = None
            continue

        if current is not None:
            fm = _FIELD_RE.match(stripped)
            if fm:
                current[fm.group("key").lower()] = fm.group("value").strip()
                continue

        m = _ENTRY_RE.match(stripped)
        if m:
            topic = m.group("topic").strip()
            lesson = m.group("lesson").strip()
            if topic and lesson:
                entries.append({"topic": topic, "lesson": lesson})

    if current:
        entries.append(current)

    # `lesson` is what search() and render_markdown() read; for block entries it
    # is the "why" (falling back to the decision) so both shapes are searchable.
    for e in entries:
        if not e.get("lesson"):
            e["lesson"] = e.get("why") or e.get("decision") or ""

    return [e for e in entries if e.get("topic") and e.get("lesson")]


def search(query: str, top_k: int = 5) -> list[dict]:
    """Search negative-knowledge entries by simple keyword scoring.

    The query is split into words (case-insensitive).  Each entry is scored
    by the number of query words that appear as substrings in the topic and
    lesson fields.  The top *top_k* matches (by score, ties resolved by
    original document order) are returned; entries with zero matches are
    excluded.

    Parameters
    ----------
    query:
        Free-text search query.
    top_k:
        Maximum number of entries to return.  Default ``5``.

    Returns
    -------
    list[dict]
        List of ``{"topic": ..., "lesson": ..., "score": ...}`` dicts.
    """
    words = [w.lower() for w in re.findall(r"\w+", query or "")]
    if not words:
        return []

    entries = load_entries()
    scored: list[tuple[int, int, dict]] = []
    for index, entry in enumerate(entries):
        haystack = (entry["topic"] + " " + entry["lesson"]).lower()
        score = sum(1 for w in words if w in haystack)
        if score > 0:
            scored.append((score, index, entry))

    # Sort by descending score, then ascending original index (stable ties).
    scored.sort(key=lambda t: (-t[0], t[1]))

    results = []
    for score, index, entry in scored[:top_k]:
        results.append({**entry, "score": score})
    return results


def render_markdown(entries: list[dict]) -> str:
    """Render entries back into ``- **<topic>**: <lesson>`` markdown lines.

    Any extra keys (e.g. ``score``) are ignored.
    """
    lines = []
    for entry in entries:
        topic = str(entry.get("topic", "")).strip()
        lesson = str(entry.get("lesson", "")).strip()
        if topic and lesson:
            lines.append(f"- **{topic}**: {lesson}")
    return "\n".join(lines)


def main() -> None:
    """CLI entry point for negative-knowledge helpers."""
    parser = argparse.ArgumentParser(description="Negative knowledge helpers.")
    parser.add_argument("--search", help="Search query for negative-knowledge entries.")
    parser.add_argument("--list", action="store_true", help="List all entries.")
    parser.add_argument("--top-k", type=int, default=5, help="Max results for --search (default: 5).")
    args = parser.parse_args()

    if args.search:
        hits = search(args.search, top_k=args.top_k)
        for hit in hits:
            extra = ""
            if "score" in hit:
                extra = f" [score={hit['score']}]"
            print(f"- **{hit['topic']}**: {hit['lesson']}{extra}")
        return

    if args.list:
        print(render_markdown(load_entries()))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
