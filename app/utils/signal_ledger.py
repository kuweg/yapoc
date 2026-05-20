"""Signal ledger — tracks evaluator findings across rounds.

Closes the verification loop and feeds the goal proposer. Without this,
the evaluator reflags the same issue indefinitely — observed live with
"Doctor cooldown fix proposed in rounds 22-24, still NOT applied" in
REPORT.MD. The ledger turns that narrative observation into a structured
counter the goal proposer (and any other consumer) can act on.

Flow:
  1. Evaluator writes a new round to ``app/agents/evaluator/REPORT.MD``.
  2. ``scan_findings()`` walks the last few rounds, extracts numbered
     "Top issues", and computes a stable ``signal_id`` per issue
     (``sha256(source_path + impact + first-120-chars-of-text)[:12]``)
     so the same issue produces the same id every round even if the
     evaluator paraphrases the headline.
  3. ``update_ledger()`` increments ``rounds_open`` for signals still
     present and marks signals absent from the latest round as
     ``resolved`` (with ``resolved_at`` stamp + ``rounds_open_final``).
  4. ``get_persistent(min_rounds)`` returns signals open at least N
     consecutive rounds — what the goal proposer turns into Proposed
     GOALS.MD entries.

Storage: ``data/signal_ledger.json`` — a single dict keyed by
signal_id. Append-only in spirit (resolved entries stay around) so the
proposer can refuse duplicates and the user can see history.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


_LEDGER_PATH = settings.project_root / "data" / "signal_ledger.json"
_REPORT_PATH = settings.agents_dir / "evaluator" / "REPORT.MD"

# How many of the most-recent rounds to scan when updating the ledger.
# 5 is enough to recognize a persistent signal coming back after a
# transient absence (e.g. evaluator skipped a round due to budget),
# while still bounding the I/O.
_LOOKBACK_ROUNDS = 5

# Round header regex — matches "## YYYY-MM-DD HH:MM — Self-evaluation (round N)"
_ROUND_HEADER_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2}[^—]*)—\s*Self-evaluation\s*\(round\s+(\d+)\)",
    re.MULTILINE | re.IGNORECASE,
)

# Stopwords + filler that don't disambiguate one issue from another.
# Anything in the bag below is dropped before hashing.
_SIGNAL_ID_STOPWORDS: frozenset[str] = frozenset({
    # English stopwords
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "for", "by",
    "with", "from", "as", "that", "this", "it", "its", "if", "than",
    "then", "so", "still", "not", "no", "yes", "do", "does", "did",
    # Evaluator narrative cruft + ordinal/temporal noise
    "round", "rounds", "ago", "now", "yet", "again", "also",
    "proposed", "implemented", "applied", "fix", "fixes", "fixed",
    "issue", "issues", "problem", "problems",
})

# Tokens that look like rounds-N markers or numbers — strip them too,
# otherwise "round 22" vs "round 25" defeat the stable-id intent.
_SIGNAL_ID_NUMERIC_RE = re.compile(r"^\d+$")
_SIGNAL_ID_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]+")


def _signal_id_from_title(title: str) -> str:
    """Hash the significant-word bag of a finding title.

    Steps:
      1. Lowercase + extract word tokens (drop punctuation / mdash / numbers).
      2. Drop stopwords + ordinal/numeric tokens.
      3. Sort the resulting set so word order doesn't matter.
      4. Take the first 6 (or all if fewer) — caps the hash input.
      5. SHA-256 → first 12 hex chars.

    Designed for stability across round-to-round paraphrase. Two issues
    with very similar significant-word bags will collide; that's the
    intended behavior (they're the SAME issue).
    """
    raw_tokens = _SIGNAL_ID_WORD_RE.findall(title.lower())
    sig = sorted({
        t for t in raw_tokens
        if t not in _SIGNAL_ID_STOPWORDS
        and not _SIGNAL_ID_NUMERIC_RE.fullmatch(t)
        and len(t) > 2
    })
    # Take a bounded prefix so a long title doesn't dilute the hash with
    # late-added narrative words ("— still not applied as of round 25").
    sig_prefix = sig[:6]
    if not sig_prefix:
        # Defensive: a title made entirely of stopwords/numbers — fall
        # back to the raw lowered title so we don't collide everything.
        sig_prefix = [title.lower().strip()[:60]]
    payload = "|".join(sig_prefix).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]

# Issue entry regex inside "### Top issues" — matches numbered entries
# of the form: ``1. **Title — issue summary** — Impact: HIGH``.
_ISSUE_RE = re.compile(
    r"^\s*\d+\.\s+\*\*(.+?)\*\*\s*(?:—|--)\s*Impact:\s*(HIGH|MEDIUM|LOW)",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass
class ParsedFinding:
    """One Top-Issue entry extracted from a single REPORT.MD round."""
    round_number: int
    round_ts: str            # raw timestamp string from the header
    title: str               # the text inside ** ** before the Impact tag
    impact: str              # HIGH / MEDIUM / LOW
    body_preview: str        # first ~400 chars of the body for ID stability + context

    def signal_id(self) -> str:
        """Stable id across rounds — same issue reworded slightly still matches.

        Hashes a normalized *token bag* of significant words from the
        title. Word-bag stability survives reordering and "— suffix
        added in round N" rewrites: "Doctor alert fatigue cooldown"
        and "Doctor alert fatigue — cooldown still not implemented"
        share enough significant words to collide deterministically.
        """
        return _signal_id_from_title(self.title)


@dataclass
class LedgerEntry:
    signal_id: str
    title: str
    impact: str
    first_seen_round: int
    first_seen_ts: str
    last_seen_round: int
    last_seen_ts: str
    rounds_open: int
    status: str = "open"          # "open" | "resolved"
    resolved_round: int | None = None
    resolved_ts: str | None = None
    # Track which rounds we've seen this signal in, so a transient
    # one-round absence doesn't reset the persistence count completely.
    seen_in_rounds: list[int] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_ledger() -> dict[str, dict]:
    if not _LEDGER_PATH.exists():
        return {}
    try:
        return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_ledger(data: dict[str, dict]) -> None:
    try:
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LEDGER_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_LEDGER_PATH)
    except OSError:
        pass  # best-effort: ledger is recoverable from REPORT.MD anyway


def scan_findings(report_path: Path | None = None, lookback: int = _LOOKBACK_ROUNDS) -> list[ParsedFinding]:
    """Parse the last ``lookback`` rounds out of REPORT.MD.

    REPORT.MD has rounds newest-first (the evaluator prepends), so we
    take the first ``lookback`` round-headers found. Each round's
    "Top issues" numbered list is scanned for ``**title** — Impact: X``
    headers, with a 400-char tail of the body for ID stability.
    """
    report_path = report_path or _REPORT_PATH
    if not report_path.exists():
        return []
    text = report_path.read_text(encoding="utf-8")

    # Locate all round headers + their start indices.
    headers: list[tuple[int, str, int]] = []  # (start_idx, ts, round_num)
    for m in _ROUND_HEADER_RE.finditer(text):
        headers.append((m.start(), m.group(1).strip(), int(m.group(2))))
    if not headers:
        return []

    findings: list[ParsedFinding] = []
    for i, (start, ts, round_num) in enumerate(headers[:lookback]):
        end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        round_text = text[start:end]
        for m in _ISSUE_RE.finditer(round_text):
            title = m.group(1).strip()
            impact = m.group(2).upper()
            # Body preview: 400 chars after the matched header line.
            body_start = m.end()
            body_end = min(body_start + 400, len(round_text))
            body_preview = round_text[body_start:body_end].strip()
            findings.append(ParsedFinding(
                round_number=round_num,
                round_ts=ts,
                title=title,
                impact=impact,
                body_preview=body_preview,
            ))
    return findings


def update_ledger(findings: list[ParsedFinding] | None = None) -> dict[str, LedgerEntry]:
    """Update the on-disk ledger from the latest REPORT.MD round(s).

    Increments ``rounds_open`` and updates ``last_seen_*`` for signals
    still present. Marks signals not in the latest round as ``resolved``.

    Returns the ledger keyed by signal_id (LedgerEntry instances).
    """
    if findings is None:
        findings = scan_findings()
    raw = _load_ledger()

    # Determine the most-recent round we have data for; signals absent
    # from THIS round get marked resolved.
    rounds_seen = sorted({f.round_number for f in findings}, reverse=True)
    if not rounds_seen:
        return {sid: LedgerEntry(**entry) for sid, entry in raw.items()}
    latest_round = rounds_seen[0]
    in_latest: set[str] = set()

    for f in findings:
        sid = f.signal_id()
        if f.round_number == latest_round:
            in_latest.add(sid)
        entry = raw.get(sid)
        if entry is None:
            raw[sid] = {
                "signal_id": sid,
                "title": f.title,
                "impact": f.impact,
                "first_seen_round": f.round_number,
                "first_seen_ts": f.round_ts,
                "last_seen_round": f.round_number,
                "last_seen_ts": f.round_ts,
                "rounds_open": 1,
                "status": "open",
                "resolved_round": None,
                "resolved_ts": None,
                "seen_in_rounds": [f.round_number],
            }
        else:
            # Reopen if it was previously marked resolved.
            if entry.get("status") == "resolved":
                entry["status"] = "open"
                entry["resolved_round"] = None
                entry["resolved_ts"] = None
            if f.round_number not in entry["seen_in_rounds"]:
                entry["seen_in_rounds"].append(f.round_number)
            entry["seen_in_rounds"] = sorted(set(entry["seen_in_rounds"]))[-20:]
            entry["last_seen_round"] = max(entry["last_seen_round"], f.round_number)
            entry["last_seen_ts"] = f.round_ts
            entry["rounds_open"] = len(entry["seen_in_rounds"])
            entry["impact"] = f.impact  # refresh in case evaluator re-classified
            entry["title"] = f.title

    # Mark signals not in the latest round as resolved.
    for sid, entry in raw.items():
        if entry["status"] == "open" and sid not in in_latest:
            # Only resolve if the most-recent round we processed includes
            # this signal's expected round and it's absent. Avoid
            # accidentally resolving on a partial scan.
            if entry["last_seen_round"] < latest_round:
                entry["status"] = "resolved"
                entry["resolved_round"] = latest_round
                entry["resolved_ts"] = _now_iso()

    _save_ledger(raw)
    return {sid: LedgerEntry(**entry) for sid, entry in raw.items()}


def get_persistent(min_rounds: int = 3) -> list[LedgerEntry]:
    """Return signals open across at least ``min_rounds`` consecutive
    evaluator rounds (still status='open' at last scan)."""
    raw = _load_ledger()
    out: list[LedgerEntry] = []
    for entry in raw.values():
        if entry.get("status") != "open":
            continue
        if int(entry.get("rounds_open", 0)) >= min_rounds:
            out.append(LedgerEntry(**entry))
    # Most-stuck first (most rounds open), tiebreaker = highest impact.
    _IMPACT_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out.sort(key=lambda e: (-e.rounds_open, _IMPACT_ORDER.get(e.impact.upper(), 3)))
    return out


def ledger_snapshot() -> dict:
    """Cheap summary suitable for surfacing in the UI or yapoc status."""
    raw = _load_ledger()
    return {
        "total": len(raw),
        "open": sum(1 for e in raw.values() if e.get("status") == "open"),
        "resolved": sum(1 for e in raw.values() if e.get("status") == "resolved"),
        "persistent_3plus": sum(
            1 for e in raw.values()
            if e.get("status") == "open" and int(e.get("rounds_open", 0)) >= 3
        ),
    }


__all__ = [
    "scan_findings",
    "update_ledger",
    "get_persistent",
    "ledger_snapshot",
    "ParsedFinding",
    "LedgerEntry",
]
