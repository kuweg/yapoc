"""Phase 3.4 — recommend a delegation target from measured history.

Routing has been a prompt-level judgment call by master. Phases 1 and 2 made the
inputs for a better decision available for the first time: per-agent success
rate, cost and duration, all recorded per task.

Measured over 30 days, the case for routing concrete implementation work
straight to builder is no longer a preference:

    builder    n=236  success 97%  avg $0.0103  avg  37s
    planning   n=80   success 85%  avg $0.0288  avg  84s

Planning costs ~2.8x more, takes ~2.3x longer, and fails ~4x as often. For work
that needs no decomposition, routing through it buys nothing and costs all three.

## This advises; it does not override

`recommend()` returns a recommendation with its evidence. It is deliberately not
wired to silently rewrite master's delegation, for two reasons:

1. The classifier is a heuristic over prompt text. Acting on it silently would
   turn a misclassification into a wrong route with no trace.
2. Orchestration that changes based on a moving statistic is hard to debug when
   it goes wrong; a recommendation with a stated reason keeps the decision
   legible in the transcript.

## Thin history yields no recommendation

Below `MIN_SAMPLES` the function returns the configured default and says why.
A routing decision from four data points is noise wearing a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

TaskClass = Literal[
    "concrete_implementation",
    "ambiguous_decomposition",
    "research",
    "config",
    "maintenance",
    "unknown",
]

# Below this, an agent's history is not evidence.
MIN_SAMPLES = 10

# Where each class goes when history is unavailable or inconclusive. These are
# the existing conventions, so falling back changes nothing.
DEFAULT_TARGETS: dict[str, str] = {
    "concrete_implementation": "builder",
    "ambiguous_decomposition": "planning",
    "research": "researcher",
    "config": "keeper",
    "maintenance": "builder",
    "unknown": "planning",
}

# Signals that a task already says what to do (concrete), versus signals that it
# describes an outcome and leaves the steps open (ambiguous).
_CONCRETE_MARKERS = (
    r"\bcreate (?:the |a )?file\b", r"\badd (?:a |the )?(?:function|method|endpoint|test|button|column|field)\b",
    r"\bfix\b", r"\brename\b", r"\bdelete\b", r"\bupdate (?:the )?\w+\.(py|ts|tsx|json|yaml|md)\b",
    r"\bin ([\w/\.]+\.(py|ts|tsx|json|yaml|md))\b", r"\brun\b.*\bcommand\b",
    r"\bimplement (?:the )?\w+ (?:function|method|endpoint|flag|option)\b",
)
_AMBIGUOUS_MARKERS = (
    r"\bfigure out\b", r"\binvestigate\b", r"\bdesign\b", r"\bplan\b", r"\bdecide\b",
    r"\bwork out\b", r"\bhow (?:should|do) we\b", r"\bapproach\b", r"\bstrategy\b",
    r"\brefactor the (?:whole|entire)\b", r"\bend[- ]to[- ]end\b", r"\barchitecture\b",
)
_RESEARCH_MARKERS = (r"\bresearch\b", r"\bsearch the web\b", r"\bfind out\b",
                     r"\bdocumentation for\b", r"\bcompare\b.*\boptions\b", r"\bhttps?://")
_CONFIG_MARKERS = (r"\.env\b", r"\bagent-settings\.json\b", r"\bsettings\.py\b",
                   r"\bconfigure\b", r"\bapi key\b", r"\bcredential\b", r"\btimeout\b.*\bsetting\b")
_MAINTENANCE_MARKERS = (r"\bclean ?up\b", r"\barchive\b", r"\bconsolidate\b",
                        r"\bprune\b", r"\bhealth check\b")


def classify_task(prompt: str) -> TaskClass:
    """Best-effort class for a task prompt.

    Order matters: config and research are checked before the concrete/ambiguous
    split, because "configure the API key" is concrete AND config, and the more
    specific routing is the useful one.
    """
    text = (prompt or "").lower()
    if not text.strip():
        return "unknown"

    def hits(patterns) -> int:
        return sum(1 for p in patterns if re.search(p, text))

    if hits(_CONFIG_MARKERS):
        return "config"
    if hits(_RESEARCH_MARKERS):
        return "research"
    if hits(_MAINTENANCE_MARKERS):
        return "maintenance"

    concrete, ambiguous = hits(_CONCRETE_MARKERS), hits(_AMBIGUOUS_MARKERS)
    if concrete and concrete > ambiguous:
        return "concrete_implementation"
    if ambiguous and ambiguous > concrete:
        return "ambiguous_decomposition"
    return "unknown"


@dataclass
class AgentStats:
    agent: str
    tasks: int
    success_rate: float
    avg_cost_usd: float
    avg_duration_s: float

    @property
    def has_evidence(self) -> bool:
        return self.tasks >= MIN_SAMPLES


@dataclass
class Recommendation:
    task_class: TaskClass
    target: str
    reason: str
    evidence: dict[str, Any]
    from_history: bool

    def line(self) -> str:
        src = "measured" if self.from_history else "default"
        return f"{self.task_class} -> {self.target} ({src}): {self.reason}"


def agent_stats(days: int = 30, db=None) -> dict[str, AgentStats]:
    """Success rate, cost and duration per agent over a trailing window."""
    from app.utils.db import get_db, init_schema

    if db is None:
        init_schema()
        db = get_db()
    rows = db.execute(
        """SELECT agent,
                  COUNT(*) n,
                  SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) done,
                  AVG(COALESCE(cost_usd, 0)) avg_cost,
                  AVG(CASE WHEN completed_at IS NOT NULL AND assigned_at IS NOT NULL
                      THEN (julianday(completed_at)-julianday(assigned_at))*86400 END) avg_s
           FROM tasks
           WHERE assigned_at >= date('now', ?)
             AND status IN ('done','error')
           GROUP BY agent""",
        (f"-{int(days)} days",),
    ).fetchall()
    return {
        r["agent"]: AgentStats(
            agent=r["agent"],
            tasks=int(r["n"] or 0),
            success_rate=(int(r["done"] or 0) / int(r["n"])) if r["n"] else 0.0,
            avg_cost_usd=float(r["avg_cost"] or 0.0),
            avg_duration_s=float(r["avg_s"] or 0.0),
        )
        for r in rows
    }


def recommend(
    prompt: str,
    days: int = 30,
    stats: dict[str, AgentStats] | None = None,
) -> Recommendation:
    """Recommend a delegation target, with the evidence behind it."""
    task_class = classify_task(prompt)
    default = DEFAULT_TARGETS[task_class]
    stats = agent_stats(days) if stats is None else stats

    # Only concrete implementation has a real alternative to weigh: it can go
    # to builder directly or through planning. Every other class has one
    # natural home, so there is nothing to decide.
    if task_class != "concrete_implementation":
        return Recommendation(
            task_class, default,
            f"{task_class} has a single natural owner",
            {"considered": [default]}, from_history=False,
        )

    direct = stats.get("builder")
    via_planner = stats.get("planning")
    if not direct or not direct.has_evidence:
        return Recommendation(
            task_class, default,
            f"insufficient history for builder (need {MIN_SAMPLES} tasks)",
            {"builder_tasks": direct.tasks if direct else 0}, from_history=False,
        )

    evidence = {
        "builder": {"tasks": direct.tasks, "success_rate": round(direct.success_rate, 3),
                    "avg_cost_usd": round(direct.avg_cost_usd, 5),
                    "avg_duration_s": round(direct.avg_duration_s, 1)},
    }
    if via_planner and via_planner.has_evidence:
        evidence["planning"] = {
            "tasks": via_planner.tasks, "success_rate": round(via_planner.success_rate, 3),
            "avg_cost_usd": round(via_planner.avg_cost_usd, 5),
            "avg_duration_s": round(via_planner.avg_duration_s, 1),
        }
        better = (
            direct.success_rate >= via_planner.success_rate
            and direct.avg_cost_usd <= via_planner.avg_cost_usd
        )
        if better:
            return Recommendation(
                task_class, "builder",
                (
                    f"builder succeeds {direct.success_rate:.0%} at "
                    f"${direct.avg_cost_usd:.4f}/task vs planning "
                    f"{via_planner.success_rate:.0%} at ${via_planner.avg_cost_usd:.4f}; "
                    f"decomposition buys nothing here"
                ),
                evidence, from_history=True,
            )
        return Recommendation(
            task_class, "planning",
            (
                f"planning currently outperforms builder "
                f"({via_planner.success_rate:.0%} vs {direct.success_rate:.0%})"
            ),
            evidence, from_history=True,
        )

    return Recommendation(
        task_class, "builder",
        f"builder succeeds {direct.success_rate:.0%} over {direct.tasks} tasks; "
        f"no comparable planning history to weigh against",
        evidence, from_history=True,
    )


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="YAPOC routing policy")
    ap.add_argument("prompt", nargs="*", help="task prompt to classify and route")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--stats", action="store_true", help="show per-agent history")
    args = ap.parse_args()

    if args.stats or not args.prompt:
        for name, st in sorted(agent_stats(args.days).items(),
                               key=lambda kv: -kv[1].tasks):
            flag = "" if st.has_evidence else "  (thin history)"
            print(f"  {name:<20} n={st.tasks:<4} success={st.success_rate:.0%} "
                  f"avg=${st.avg_cost_usd:.5f} {st.avg_duration_s:.0f}s{flag}")
        if not args.prompt:
            return
        print()

    rec = recommend(" ".join(args.prompt), days=args.days)
    print(rec.line())
    print(json.dumps(rec.evidence, indent=2))


if __name__ == "__main__":
    main()
