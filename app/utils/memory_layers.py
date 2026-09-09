"""Phase 3.1 — typed memory layers, retention policy, and repetition collapse.

Until now every memory row was one undifferentiated kind of thing, separated
only by `tier` (hot/cold) for retrieval visibility. That made lifecycle policy
impossible to express: a user preference and a routine health-check line aged
out at the same rate, and retrieval ranked them the same way.

## Why `layer` is a new column rather than new `tier` values

The roadmap proposed extending `tier` from hot/cold to the layer names. `tier`
is load-bearing in retrieval — `search_fts`, `search_vector` and `search_hybrid`
all filter on `tier = 'hot'` — so redefining its values would silently change
what every query returns. The two concepts are also genuinely different:

    tier   RETRIEVAL VISIBILITY  hot | cold      (is this searchable now?)
    layer  KIND OF MEMORY        episodic | ...  (what sort of thing is this?)

Keeping them separate means a row can be, say, `project`-layer but `cold`-tier
after collapse, which is exactly what the repetition policy below needs.

## The problem this exists to fix

The Phase 2.4 retrieval benchmark found that repetitive low-signal entries
outrank specific matches on sheer volume: the query "security audit findings"
returned five `model_audit: N agents scanned` rows instead of the two real
findings. Measured against the live database, **58.2% of hot memory rows
(1,460 of 2,510) are near-duplicates** of each other — 786 of them are the
single line `health_check: ISSUES DETECTED — N issue(s)`.

Collapse keeps the newest occurrence of each repeated shape, annotates it with
how many times it happened, and demotes the rest to `cold`. Nothing is deleted:
the rows stay in the table and stay reachable with `include_cold=True`, matching
the existing decay utility's posture of archiving rather than destroying.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ── Layers ──────────────────────────────────────────────────────────────────

WORKING = "working"        # scratch state for a task in flight; shortest life
EPISODIC = "episodic"      # what happened: task/result logs, reports
PROJECT = "project"        # durable facts about the system and its conventions
PREFERENCE = "preference"  # what the user wants; effectively permanent
ARCHIVAL = "archival"      # already archived out of the live logs

LAYERS: tuple[str, ...] = (WORKING, EPISODIC, PROJECT, PREFERENCE, ARCHIVAL)

# Retention in days per layer. `None` means "never expire on age alone".
# Preferences never age out: a user stating how they want things done stays
# true until they say otherwise, and quietly forgetting it is a worse failure
# than holding a stale one.
RETENTION_DAYS: dict[str, int | None] = {
    WORKING: 2,
    EPISODIC: 30,
    PROJECT: 180,
    PREFERENCE: None,
    ARCHIVAL: None,
}

# Source file -> layer. Checked by exact source name first, then by the
# agent/source pairing, so a rule can be specific without being brittle.
_SOURCE_LAYERS: dict[str, str] = {
    "MEMORY.MD": EPISODIC,
    "TASK.MD": EPISODIC,
    "REPORT.MD": EPISODIC,
    "HEALTH.MD": EPISODIC,
    "NOTES.MD": PROJECT,
    "LEARNINGS.MD": PROJECT,
    "KNOWLEDGE.MD": PROJECT,
    "PROFILE.md": PREFERENCE,
    "HISTORY.md": PREFERENCE,
}


def classify_layer(agent: str, source: str, content: str = "", tier: str = "hot") -> str:
    """Assign a memory layer from where an entry came from.

    Source is the primary signal because it reflects the author's intent:
    NOTES.MD is where an agent records something it wants to keep, MEMORY.MD is
    an append-only log of what it did. Content is only consulted to catch the
    session-scratch case, which has no distinct source of its own.
    """
    if tier == "cold":
        return ARCHIVAL
    if agent == "user":
        return PREFERENCE
    if agent == "_session":
        return WORKING
    layer = _SOURCE_LAYERS.get(source)
    if layer:
        return layer
    if source.endswith(".jsonl") or "session" in source.lower():
        return WORKING
    # Unknown sources are episodic: it is the middle retention, so an
    # unclassified row is neither forgotten quickly nor kept forever.
    return EPISODIC


# ── Repetition detection ────────────────────────────────────────────────────

# Order matters: UUIDs and timestamps are matched before bare digits, or the
# digit rule would shred them into an unrecognizable shape.
_SHAPE_SUBSTITUTIONS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<uuid>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?Z?"), "<ts>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hash>"),
    (re.compile(r"\$?\d+(?:\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
)

# Shapes shorter than this carry too little structure for a match to mean
# "the same kind of entry" — collapsing on them would merge unrelated rows.
_MIN_SHAPE_LEN = 24


def shape_key(content: str, prefix: int = 120) -> str:
    """Normalize an entry to a comparable 'shape'.

    `health_check: ISSUES DETECTED — 7 issue(s)` and `... — 12 issue(s)` differ
    only in a number, so they share a shape and are the same kind of entry.
    Numbers, UUIDs, timestamps and hashes are the fields that vary between
    otherwise-identical log lines, so they are exactly what gets erased.
    """
    text = (content or "").strip()
    for pattern, replacement in _SHAPE_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text[:prefix].strip().lower()


@dataclass
class RepetitionGroup:
    agent: str
    source: str
    shape: str
    ids: list[int] = field(default_factory=list)
    representative_id: int | None = None
    sample: str = ""

    @property
    def count(self) -> int:
        return len(self.ids)

    @property
    def collapsed_ids(self) -> list[int]:
        """Ids to demote — everything except the representative."""
        return [i for i in self.ids if i != self.representative_id]


def find_repetition_groups(
    rows: Iterable[dict[str, Any]], min_count: int = 3
) -> list[RepetitionGroup]:
    """Group rows that are the same kind of entry repeated.

    Grouped by (agent, source, shape) rather than shape alone: two agents
    logging structurally similar lines are still separate facts, and collapsing
    across agents would lose which agent it happened to.

    The newest row in a group becomes the representative, because for a
    repeated status line the latest value is the one worth retrieving.
    """
    buckets: dict[tuple[str, str, str], RepetitionGroup] = {}
    order: dict[int, str] = {}

    for row in rows:
        content = row.get("content", "") or ""
        shape = shape_key(content)
        if len(shape) < _MIN_SHAPE_LEN:
            continue
        key = (row.get("agent", ""), row.get("source", ""), shape)
        group = buckets.get(key)
        if group is None:
            group = RepetitionGroup(agent=key[0], source=key[1], shape=shape, sample=content)
            buckets[key] = group
        group.ids.append(int(row["id"]))
        order[int(row["id"])] = str(row.get("timestamp", "") or "")

    groups = [g for g in buckets.values() if g.count >= min_count]
    for group in groups:
        # Newest wins; ties broken by the higher row id (later insert).
        group.representative_id = max(group.ids, key=lambda i: (order.get(i, ""), i))
    return groups


def annotate_representative(content: str, count: int) -> str:
    """Mark the surviving row with how many times its shape occurred.

    Retrieval otherwise loses the fact that something happened 786 times, which
    is itself the signal — a health check firing that often is a story about the
    system, even though 785 of the rows are not worth returning.
    """
    stripped = (content or "").rstrip()
    marker = f"[x{count} occurrences]"
    if marker in stripped:
        return stripped
    return f"{stripped}\n{marker}"


# ── Database operations ─────────────────────────────────────────────────────


@dataclass
class CollapseReport:
    groups: int = 0
    collapsed: int = 0
    scanned: int = 0
    dry_run: bool = True

    def summary(self) -> str:
        verb = "would collapse" if self.dry_run else "collapsed"
        return (
            f"{verb} {self.collapsed} of {self.scanned} hot rows "
            f"across {self.groups} repetition group(s)"
        )


def backfill_layers(db=None) -> int:
    """Assign a layer to rows written before the column existed. Idempotent."""
    from app.utils.db import get_db

    db = db or get_db()
    rows = db.execute(
        "SELECT id, agent, source, tier, layer FROM memory_entries"
    ).fetchall()
    updated = 0
    for row in rows:
        want = classify_layer(row["agent"], row["source"], "", row["tier"])
        if (row["layer"] or "") != want:
            db.execute(
                "UPDATE memory_entries SET layer = ? WHERE id = ?", (want, row["id"])
            )
            updated += 1
    db.commit()
    return updated


def collapse_repetitions(
    db=None,
    min_count: int = 3,
    dry_run: bool = True,
    agent: str | None = None,
) -> CollapseReport:
    """Demote near-duplicate hot rows to cold, keeping one annotated survivor.

    Deliberately non-destructive: collapsed rows keep their content and stay
    reachable with ``include_cold=True``. Only their retrieval visibility
    changes, which is the thing that was harming search quality.

    Defaults to ``dry_run=True`` — a function that quietly rewrites more than
    half of memory should require an explicit decision to actually do it.
    """
    from app.utils.db import get_db

    db = db or get_db()
    query = "SELECT id, agent, source, content, timestamp FROM memory_entries WHERE tier = 'hot'"
    params: list[Any] = []
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    rows = [dict(r) for r in db.execute(query, params).fetchall()]

    groups = find_repetition_groups(rows, min_count=min_count)
    report = CollapseReport(
        groups=len(groups),
        collapsed=sum(len(g.collapsed_ids) for g in groups),
        scanned=len(rows),
        dry_run=dry_run,
    )
    if dry_run or not groups:
        return report

    by_id = {r["id"]: r for r in rows}
    for group in groups:
        rep_id = group.representative_id
        if rep_id is None:
            continue
        rep = by_id.get(rep_id)
        if rep is not None:
            annotated = annotate_representative(rep["content"], group.count)
            db.execute(
                "UPDATE memory_entries SET content = ? WHERE id = ?", (annotated, rep_id)
            )
            db.execute("UPDATE memory_fts SET content = ? WHERE rowid = ?", (annotated, rep_id))
        for dead_id in group.collapsed_ids:
            db.execute(
                "UPDATE memory_entries SET tier = 'cold', layer = ? WHERE id = ?",
                (ARCHIVAL, dead_id),
            )
    db.commit()
    return report


def layer_stats(db=None) -> dict[str, dict[str, int]]:
    """Row counts per layer and tier — the observable side of the policy."""
    from app.utils.db import get_db

    db = db or get_db()
    stats: dict[str, dict[str, int]] = {}
    for row in db.execute(
        "SELECT layer, tier, COUNT(*) n FROM memory_entries GROUP BY layer, tier"
    ):
        stats.setdefault(row["layer"] or "unknown", {})[row["tier"]] = row["n"]
    return stats


def main() -> None:
    """CLI: inspect layers and run the repetition collapse.

        poetry run python -m app.utils.memory_layers --stats
        poetry run python -m app.utils.memory_layers --collapse          # dry run
        poetry run python -m app.utils.memory_layers --collapse --apply  # for real
    """
    import argparse
    import json

    from app.utils.db import init_schema

    ap = argparse.ArgumentParser(description="YAPOC memory layers")
    ap.add_argument("--stats", action="store_true", help="row counts per layer/tier")
    ap.add_argument("--backfill", action="store_true", help="assign layers to legacy rows")
    ap.add_argument("--collapse", action="store_true", help="collapse repetitive entries")
    ap.add_argument("--apply", action="store_true",
                    help="actually write changes (collapse defaults to a dry run)")
    ap.add_argument("--agent", default=None, help="limit to one agent")
    ap.add_argument("--min-count", type=int, default=3,
                    help="occurrences before a shape is considered repetitive")
    args = ap.parse_args()

    init_schema()

    if args.backfill:
        print(f"backfilled layer on {backfill_layers()} row(s)")
    if args.collapse:
        report = collapse_repetitions(
            min_count=args.min_count, dry_run=not args.apply, agent=args.agent
        )
        print(report.summary())
        if report.dry_run and report.collapsed:
            print("  (dry run — pass --apply to write)")
    if args.stats or not (args.collapse or args.backfill):
        print(json.dumps(layer_stats(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
