"""Phase 2.3 — every indexed memory row must record where it came from.

`memory_entries.provenance` existed but was written by exactly one of the eleven
index call sites, leaving it empty for 2,473 of 2,480 rows in the live database.
Retrieval could surface a memory with no way to answer "which file is this
from?", which blocks the lifecycle work in Phase 3.1 (retention and promotion
rules need to know a row's origin).
"""

from __future__ import annotations

import inspect
import re

from app.utils import indexer


def _call_blocks(source: str, func_name: str) -> list[str]:
    """Return the argument text of each call to `func_name`."""
    blocks = []
    for m in re.finditer(rf"{func_name}\(", source):
        i = source.index("(", m.start())
        start, depth = i, 0
        while True:
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks.append(source[start : i + 1])
    return blocks


def test_every_index_site_records_provenance():
    """A new index site added without provenance re-opens the dead column."""
    blocks = _call_blocks(inspect.getsource(indexer), "insert_memory_entry")
    assert blocks, "no insert_memory_entry calls found — did the indexer move?"
    missing = [b for b in blocks if "provenance=" not in b]
    assert not missing, (
        f"{len(missing)} of {len(blocks)} insert_memory_entry call(s) omit "
        f"provenance:\n" + "\n---\n".join(missing)
    )


def test_provenance_is_repo_relative(tmp_path, monkeypatch):
    """Paths are stored relative to the project root, so they stay portable."""
    from app.config import settings

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    target = tmp_path / "app" / "memory" / "agents" / "builder" / "MEMORY.MD"
    target.parent.mkdir(parents=True)
    target.write_text("x")

    assert indexer._provenance(target) == "app/memory/agents/builder/MEMORY.MD"


def test_provenance_falls_back_to_absolute_outside_the_root(tmp_path, monkeypatch):
    """A path outside the project must not raise — it degrades to absolute."""
    from app.config import settings

    monkeypatch.setattr(
        type(settings), "project_root", property(lambda self: tmp_path / "project")
    )
    (tmp_path / "project").mkdir()
    outside = tmp_path / "elsewhere" / "NOTES.MD"
    outside.parent.mkdir(parents=True)
    outside.write_text("x")

    result = indexer._provenance(outside)
    assert result.endswith("elsewhere/NOTES.MD")
    assert result.startswith("/")


def test_stored_row_carries_its_provenance(tmp_path, monkeypatch):
    """End-to-end: index a real MEMORY.MD and read the column back."""
    import sqlite3

    import app.utils.db as db_mod
    from app.config import settings

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    conn = sqlite3.connect(tmp_path / "t.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db_mod, "get_db", lambda: conn)
    monkeypatch.setattr(indexer, "embed_batch", lambda texts: [None] * len(texts))
    db_mod.init_schema()

    memory_dir = tmp_path / "app" / "memory" / "agents" / "builder"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.MD").write_text(
        "**1. [2026-09-07 10:00] did a thing | response: done\n"
    )

    written = indexer.index_agent_memory("builder", memory_dir)
    assert written >= 1, "nothing was indexed"

    rows = conn.execute(
        "SELECT provenance FROM memory_entries WHERE agent='builder'"
    ).fetchall()
    assert rows, "no rows stored"
    assert all(r["provenance"] for r in rows), "provenance left empty"
    assert all(
        r["provenance"] == "app/memory/agents/builder/MEMORY.MD" for r in rows
    ), [r["provenance"] for r in rows]
