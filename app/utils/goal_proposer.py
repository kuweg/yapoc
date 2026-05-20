"""Goal proposer — autonomous goal authoring from persistent signals.

Closes the loop the user identified: "Master pursues goals from
GOALS.MD but never *authors* them. Evaluator re-flagged the same fix
13 rounds before someone caught it." Persistent signals (open ≥
``settings.goal_proposer_min_rounds`` evaluator rounds) get written
into ``app/agents/master/GOALS.MD`` under a new ``## Proposed`` section.

Critically, autonomous proposals land in ``## Proposed`` — NOT
``## Active`` — so master's idle-check doesn't pick them up by accident
and the user gets a brake. Promotion to Active is a deliberate human
action (or a future, user-blessed automation).

Idempotency: each proposal carries its ``signal_id`` in a trailing
``<!-- signal=ABC -->`` HTML comment. Re-running the proposer never
adds a duplicate; if a signal has been promoted to Active or Done by
the user, no new ``## Proposed`` entry appears for it.

Daily cap: ``settings.goal_proposer_max_per_day`` total proposals
across a 24h rolling window (tracked via the trailing HTML comment
timestamp), so a chatty evaluator can't bury the user under proposals.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger as _log

from app.config import settings
from app.utils.signal_ledger import LedgerEntry, get_persistent, update_ledger

_GOALS_PATH = settings.agents_dir / "master" / "GOALS.MD"

# Match the ``<!-- signal=ABC ts=YYYY-... -->`` trailer we append to
# every autonomous proposal, so we can dedupe by signal_id and count
# recent proposals for the daily cap.
_PROPOSAL_TRAILER_RE = re.compile(
    r"<!--\s*signal=([0-9a-f]{6,16})\s+ts=(\S+?)\s*-->"
)

# ``## Proposed`` header — exact phrasing the proposer uses + recognizes.
_PROPOSED_HEADER = "## Proposed"
_ACTIVE_HEADER = "## Active"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_proposed_section(goals_text: str) -> str:
    """Make sure GOALS.MD has a ``## Proposed`` section, sandwiched
    between ``## Active`` and ``## Backlog`` if those exist. Returns
    the (possibly edited) full GOALS.MD text — caller writes it."""
    if _PROPOSED_HEADER in goals_text:
        return goals_text

    # Insert immediately after ``## Active`` (or its block end) so the
    # autonomous section is visually adjacent to the user's active list.
    pat = re.compile(rf"({re.escape(_ACTIVE_HEADER)}\n.*?)(?=\n## )", re.DOTALL)
    m = pat.search(goals_text)
    if m:
        insert_at = m.end()
        return goals_text[:insert_at] + f"\n{_PROPOSED_HEADER}\n_(autonomous goal proposals — move to ## Active to approve)_\n" + goals_text[insert_at:]
    # No Active section? Just append at the end (preserves Done/Backlog).
    sep = "" if goals_text.endswith("\n") else "\n"
    return goals_text + sep + f"\n{_PROPOSED_HEADER}\n_(autonomous goal proposals — move to ## Active to approve)_\n"


def _existing_signal_ids(goals_text: str) -> set[str]:
    """Every signal_id that's already represented in GOALS.MD (in any
    section). Catches both ``## Proposed`` entries the proposer wrote
    earlier AND user-promoted ones in ``## Active`` / ``## Done``."""
    return {m.group(1) for m in _PROPOSAL_TRAILER_RE.finditer(goals_text)}


def _proposals_in_last_24h(goals_text: str) -> int:
    """Count autonomous proposals whose trailer timestamp falls in the
    last 24h. Used by the daily cap so a single tick can't paste 30
    proposals at once if the ledger has a long tail."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = 0
    for m in _PROPOSAL_TRAILER_RE.finditer(goals_text):
        try:
            ts = datetime.strptime(m.group(2), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            count += 1
    return count


def _format_proposal(entry: LedgerEntry) -> str:
    """Render one LedgerEntry as a single ``- [ ]`` Proposed-section line.

    Format chosen so master can read it under the existing GOALS.MD
    rules (each goal is one line, ``- [ ]`` unchecked = active) without
    confusing the autonomous-source provenance with a user-authored
    goal — the ``[autonomous, signal=...]`` prefix is the marker."""
    seen_in = "".join([f"r{r}," for r in entry.seen_in_rounds[:8]])[:-1] or "?"
    return (
        f"- [ ] [autonomous, signal={entry.signal_id}, impact={entry.impact}] "
        f"{entry.title} (open {entry.rounds_open} evaluator rounds; "
        f"seen={seen_in}) "
        f"<!-- signal={entry.signal_id} ts={_now_iso()} -->"
    )


def _insert_into_proposed(goals_text: str, lines: list[str]) -> str:
    """Insert ``lines`` immediately under the ``## Proposed`` header,
    above whatever bullet list (if any) is already there."""
    idx = goals_text.find(_PROPOSED_HEADER)
    if idx < 0:
        # _ensure_proposed_section should have run first; defensive fallback.
        return goals_text + "\n" + "\n".join(lines) + "\n"
    # Skip past the header + the optional italic helper line so insertion
    # lands above the existing bullet list (newest first).
    after_header = goals_text.find("\n", idx) + 1
    # Skip the helper line if present
    next_line_end = goals_text.find("\n", after_header)
    helper_line = goals_text[after_header:next_line_end] if next_line_end > 0 else ""
    if helper_line.startswith("_("):
        insert_at = next_line_end + 1
    else:
        insert_at = after_header
    payload = "\n".join(lines) + "\n"
    return goals_text[:insert_at] + payload + goals_text[insert_at:]


def propose_goals(
    min_rounds: int | None = None,
    max_per_day: int | None = None,
    refresh_ledger: bool = True,
) -> dict:
    """Scan the signal ledger and emit Proposed goals for persistent
    signals.

    Returns a summary dict — useful for the CLI subcommand and the
    APScheduler tick log line. Does NOT raise on missing GOALS.MD;
    the file is created if needed.
    """
    min_rounds = int(min_rounds if min_rounds is not None else getattr(settings, "goal_proposer_min_rounds", 3))
    max_per_day = int(max_per_day if max_per_day is not None else getattr(settings, "goal_proposer_max_per_day", 3))

    if refresh_ledger:
        # Pull a fresh sweep of REPORT.MD before deciding — keeps the
        # proposer in sync with the latest evaluator round even if the
        # ledger hasn't been touched yet.
        try:
            update_ledger()
        except Exception as exc:
            _log.warning("goal_proposer: ledger refresh failed: {}", exc)

    persistent = get_persistent(min_rounds=min_rounds)
    if not persistent:
        return {"persistent": 0, "proposed": 0, "skipped": 0, "reason": "no persistent signals"}

    goals_text = _GOALS_PATH.read_text(encoding="utf-8") if _GOALS_PATH.exists() else "# GOALS\n\n## Active\n\n## Backlog\n\n## Done\n"
    goals_text = _ensure_proposed_section(goals_text)

    existing = _existing_signal_ids(goals_text)
    recent_count = _proposals_in_last_24h(goals_text)
    budget = max(0, max_per_day - recent_count)

    proposed: list[str] = []
    skipped_dupe: list[str] = []
    skipped_capped: list[str] = []
    for entry in persistent:
        if entry.signal_id in existing:
            skipped_dupe.append(entry.signal_id)
            continue
        if len(proposed) >= budget:
            skipped_capped.append(entry.signal_id)
            continue
        proposed.append(_format_proposal(entry))

    if proposed:
        goals_text = _insert_into_proposed(goals_text, proposed)
        try:
            _GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _GOALS_PATH.with_suffix(".md.tmp")
            tmp.write_text(goals_text, encoding="utf-8")
            tmp.replace(_GOALS_PATH)
        except OSError as exc:
            _log.error("goal_proposer: failed to write GOALS.MD ({})", exc)
            return {
                "persistent": len(persistent), "proposed": 0,
                "skipped_duplicate": len(skipped_dupe),
                "skipped_daily_cap": len(skipped_capped),
                "error": f"write failed: {exc}",
            }
        _log.info(
            "goal_proposer: wrote {} Proposed goals (dupe={}, daily-cap-skipped={})",
            len(proposed), len(skipped_dupe), len(skipped_capped),
        )

    return {
        "persistent": len(persistent),
        "proposed": len(proposed),
        "skipped_duplicate": len(skipped_dupe),
        "skipped_daily_cap": len(skipped_capped),
        "budget_remaining": max(0, budget - len(proposed)),
        "daily_cap": max_per_day,
        "proposed_signal_ids": [
            entry.signal_id for entry in persistent
            if entry.signal_id not in existing
        ][:len(proposed)],
    }


__all__ = ["propose_goals"]
