"""Concilium routing helper — the ignition point that connects Master's
decision flow to the Concilium deliberation orchestrator.

Concilium's engine (``app/utils/concilium.py``) is complete and proven but
was ORPHANED: nothing in the real agent flow ever invoked it. This module
is the lightweight gate Master (or any planner) calls to decide whether a
task should be routed through multi-agent deliberation *before* executing.

It reuses (does NOT duplicate) the existing heuristic analyzers from
``app/utils/concilium.py``:

  - ``assess_complexity(task_description) -> int``   (1–10)
  - ``assess_risk(task_description, affected_files) -> "low"|"moderate"|"high"``

and layers a high-risk ``flags`` marker check on top.

Usage:
    from app.utils.concilium_router import should_deliberate

    do_it, rationale = should_deliberate(
        complexity=9,
        risk="high",
        flags={"deletion": True},
    )
"""

from __future__ import annotations

from typing import Sequence

# Reuse the existing Concilium analyzers — do not reimplement the heuristics.
from app.utils.concilium import assess_complexity, assess_risk

# Numeric threshold: either dimension at/above this forces deliberation.
COMPLEXITY_THRESHOLD = 9
RISK_THRESHOLD = 9

# Numeric mapping for assess_risk's string output ("high" == RISK_THRESHOLD).
_RISK_LEVEL_SCORE = {
    "low": 1,
    "moderate": 5,
    "high": RISK_THRESHOLD,
}

# High-risk markers checked in the ``flags`` dict (and the task text). If any
# is present and truthy, deliberation is required even when the numeric
# thresholds aren't crossed — these are irreversible / safety-critical actions
# where a second perspective is worth the cost.
_HIGH_RISK_FLAG_KEYS = (
    "deletion",
    "delete",
    "drop",
    "credential_rotation",
    "rotate",
    "production_data",
    "production",
    "schema_migration",
    "migration",
    "secret",
    "credentials",
    "database",
)


def _risk_to_score(risk: int | str) -> int:
    """Normalise ``risk`` (int score or "low"|"moderate"|"high") to a numeric score."""
    if isinstance(risk, bool):
        return RISK_THRESHOLD if risk else 0
    if isinstance(risk, int):
        return risk
    if isinstance(risk, str):
        return _RISK_LEVEL_SCORE.get(risk.strip().lower(), 0)
    return 0


def should_deliberate(
    complexity: int | None = None,
    risk: int | str | None = None,
    flags: dict | None = None,
    *,
    task_description: str = "",
    affected_files: Sequence[str] | None = None,
) -> tuple[bool, list[str]]:
    """Decide whether a task should route through Concilium deliberation.

    Returns ``(should_deliberate, rationale)`` where ``rationale`` is a list
    of human-readable strings describing every rule that triggered (empty when
    the decision is to NOT deliberate).

    Parameters
    ----------
    complexity:
        Optional integer complexity score (1–10). If omitted, derived from
        ``task_description`` via ``assess_complexity``.
    risk:
        Optional risk — integer (1–10) OR ``"low" | "moderate" | "high"``.
        If omitted, derived via ``assess_risk`` from ``task_description``
        and ``affected_files``.
    flags:
        Optional dict of structural risk markers (e.g. ``{"deletion": True}``,
        ``{"schema_migration": "yes"}``). Any truthy high-risk key triggers
        deliberation.
    task_description:
        The task text, used to derive complexity/risk when not provided.
    affected_files:
        Optional file list, used by ``assess_risk`` when ``risk`` is omitted.

    Examples
    --------
    >>> should_deliberate(complexity=2, risk="low", flags={"deletion": True})
    (True, ["flag: deletion"])
    >>> should_deliberate(complexity=9, risk="moderate")
    (True, ["complexity 9 >= 9"])
    >>> should_deliberate(complexity=3, risk="low")
    (False, [])
    """
    flags = flags or {}

    # Derive any missing numeric dimension from the existing analyzers.
    if complexity is None:
        complexity = assess_complexity(task_description or "")
    if risk is None:
        risk = assess_risk(task_description or "", list(affected_files) if affected_files else None)

    risk_score = _risk_to_score(risk)
    rationale: list[str] = []

    if complexity >= COMPLEXITY_THRESHOLD:
        rationale.append(f"complexity {complexity} >= {COMPLEXITY_THRESHOLD}")

    if risk_score >= RISK_THRESHOLD:
        rationale.append(f"risk {risk_score} >= {RISK_THRESHOLD}")

    # High-risk structural markers from the flags dict. These are checked on
    # key names AND on a joined task text so a flag like {"delete": True} or a
    # bare task mentioning "drop the users table" both trip correctly.
    if flags:
        for key in _HIGH_RISK_FLAG_KEYS:
            for k, v in flags.items():
                k_lower = str(k).strip().lower()
                if key in k_lower and v:
                    rationale.append(f"flag: {k}")
                    break

    task_lower = (task_description or "").lower()
    for key in _HIGH_RISK_FLAG_KEYS:
        if key in task_lower:
            rationale.append(f"task marker: {key}")

    return len(rationale) > 0, rationale
