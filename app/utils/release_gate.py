"""Phase 3.6 — block a release when reliability, cost or retrieval regress.

Phases 1 and 2 made the system's health measurable. A measurement nobody acts on
is a dashboard, not a gate: without this, every threshold in the roadmap depends
on a human remembering to check it before shipping.

The gate reads the same sources as the Observability surfaces — no separate
accounting that could drift from what the UI shows — and exits non-zero when a
threshold is breached, so CI or a pre-release script can stop on it.

## Design notes

**Thresholds live in a checked-in file** (`release_gates.json`), not in code, so
raising or lowering a bar is a reviewable diff with a reason attached rather
than an edit buried in a function.

**An empty window is not a pass.** A gate that reports "0 failures" because no
tasks ran would wave through a completely broken system. Checks with too little
data return `SKIPPED` and say so, and `--strict` turns a skip into a failure for
a release where silence is unacceptable.

**Retrieval is checked separately** because it needs the embedding model. It is
skipped rather than failed when the model is unavailable, for the same reason
the benchmark tests skip: an offline CI runner should not look like a quality
regression.

Usage:
    poetry run python -m app.utils.release_gate                 # human output
    poetry run python -m app.utils.release_gate --json          # machine output
    poetry run python -m app.utils.release_gate --strict        # skips fail too
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_THRESHOLDS = (
    Path(__file__).resolve().parents[2] / "release_gates.json"
)

Verdict = Literal["PASS", "FAIL", "SKIPPED"]


@dataclass
class Check:
    name: str
    verdict: Verdict
    detail: str
    observed: Any = None
    threshold: Any = None

    @property
    def failed(self) -> bool:
        return self.verdict == "FAIL"

    def line(self) -> str:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIPPED": "SKIP"}[self.verdict]
        return f"[{mark}] {self.name}: {self.detail}"


@dataclass
class GateReport:
    checks: list[Check] = field(default_factory=list)
    strict: bool = False

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "FAIL"]

    @property
    def skips(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "SKIPPED"]

    @property
    def passed(self) -> bool:
        if self.failures:
            return False
        return not (self.strict and self.skips)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "strict": self.strict,
            "checks": [
                {
                    "name": c.name, "verdict": c.verdict, "detail": c.detail,
                    "observed": c.observed, "threshold": c.threshold,
                }
                for c in self.checks
            ],
        }


def _run_sync(coro):
    """Run a coroutine from sync code, whether or not a loop is already running.

    `asyncio.run()` raises inside a running loop, and the surrounding
    `except Exception` would have turned that into a SKIPPED check — a gate that
    silently stops checking when called from async code is exactly the kind of
    quiet rubber stamp this module exists to avoid.
    """
    import asyncio
    import concurrent.futures

    # Always run in a worker thread, even when the caller has no loop of its
    # own. `asyncio.run()` clears the calling thread's current event loop on
    # exit — a side effect a reporting helper has no business having. Calling
    # it directly here broke five unrelated tests that use
    # `asyncio.get_event_loop()`, purely by having run before them. A worker
    # thread leaves the caller's loop state exactly as it found it.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def load_thresholds(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_THRESHOLDS).read_text(encoding="utf-8"))


def _check_reliability(cfg: dict) -> list[Check]:
    """Failure rate, turn-limit failures and cost, over a trailing window."""
    from app.backend.routers import metrics as _metrics

    window = int(cfg.get("window_days", 7))
    min_tasks = int(cfg.get("min_tasks", 20))
    try:
        card = _run_sync(_metrics.get_reliability_scorecard(days=window))
    except Exception as exc:
        return [Check("reliability", "SKIPPED", f"scorecard unavailable: {exc}")]

    terminal = card.completed + card.failed
    if terminal < min_tasks:
        # Silence is not health: too few tasks to say anything either way.
        return [
            Check(
                "reliability", "SKIPPED",
                f"only {terminal} terminal task(s) in {window}d, need {min_tasks}",
                observed=terminal, threshold=min_tasks,
            )
        ]

    checks: list[Check] = []

    max_rate = float(cfg["max_failure_rate"])
    ok = card.failure_rate <= max_rate
    checks.append(Check(
        "failure_rate", "PASS" if ok else "FAIL",
        f"{card.failure_rate:.1%} over {window}d (max {max_rate:.1%}, n={terminal})",
        observed=card.failure_rate, threshold=max_rate,
    ))

    max_turn = int(cfg["max_turn_limit_failures"])
    turn_failures = int(card.failure_mix.get("turn_limit", 0))
    ok = turn_failures <= max_turn
    checks.append(Check(
        "turn_limit_failures", "PASS" if ok else "FAIL",
        f"{turn_failures} in {window}d (max {max_turn}) — continuations should "
        f"absorb these, so any is a regression of Phase 0",
        observed=turn_failures, threshold=max_turn,
    ))

    max_provider = int(cfg["max_provider_failures"])
    provider = int(card.failure_mix.get("provider_config", 0))
    ok = provider <= max_provider
    checks.append(Check(
        "provider_failures", "PASS" if ok else "FAIL",
        f"{provider} in {window}d (max {max_provider})",
        observed=provider, threshold=max_provider,
    ))

    max_cost = cfg.get("max_cost_per_completed_task")
    if max_cost is not None and card.cost_per_completed_task is not None:
        ok = card.cost_per_completed_task <= float(max_cost)
        checks.append(Check(
            "cost_per_completed_task", "PASS" if ok else "FAIL",
            f"${card.cost_per_completed_task:.4f} (max ${float(max_cost):.4f})",
            observed=card.cost_per_completed_task, threshold=max_cost,
        ))
    return checks


def _check_retrieval(cfg: dict) -> list[Check]:
    """Retrieval quality against the Phase 2.4 benchmark."""
    try:
        from app.utils.embeddings import embed_batch
        from app.utils.retrieval_benchmark import load_fixture, run_benchmark

        embed_batch(["warmup"])
    except Exception as exc:
        return [Check("retrieval", "SKIPPED", f"embedding model unavailable: {exc}")]

    try:
        result = run_benchmark(
            load_fixture(), mode="hybrid", k=5,
            embed=embed_batch, collapse=bool(cfg.get("collapse", True)),
        )
    except Exception as exc:
        return [Check("retrieval", "SKIPPED", f"benchmark failed to run: {exc}")]

    checks = []
    min_recall = float(cfg["min_recall_at_5"])
    checks.append(Check(
        "retrieval_recall", "PASS" if result.recall_at_k >= min_recall else "FAIL",
        f"recall@5={result.recall_at_k:.3f} (min {min_recall:.3f})",
        observed=result.recall_at_k, threshold=min_recall,
    ))
    min_mrr = float(cfg["min_mrr"])
    checks.append(Check(
        "retrieval_mrr", "PASS" if result.mrr >= min_mrr else "FAIL",
        f"MRR={result.mrr:.3f} (min {min_mrr:.3f})",
        observed=result.mrr, threshold=min_mrr,
    ))
    max_misses = int(cfg["max_misses"])
    checks.append(Check(
        "retrieval_misses", "PASS" if len(result.misses) <= max_misses else "FAIL",
        f"{len(result.misses)} unanswered quer(ies) (max {max_misses})",
        observed=len(result.misses), threshold=max_misses,
    ))
    return checks


def _check_telemetry_truthfulness(cfg: dict) -> list[Check]:
    """Dashboard counters must equal what the task tables hold.

    Phase 1 found the dashboard reporting 0 errors while 41 tasks had failed.
    That class of bug makes every other gate here meaningless — a system
    optimising against false health — so it is checked directly.
    """
    from app.backend.routers import metrics as _metrics

    try:
        _, failures, _ = _metrics._recent_task_incidents()
        dash = _run_sync(_metrics.get_observability_dashboard())
    except Exception as exc:
        return [Check("telemetry_reconciliation", "SKIPPED", f"unavailable: {exc}")]

    expected = sum(failures.values())
    observed = dash.totals.task_failure_count
    ok = observed == expected
    return [Check(
        "telemetry_reconciliation", "PASS" if ok else "FAIL",
        f"dashboard reports {observed} task failures, tables hold {expected}",
        observed=observed, threshold=expected,
    )]


def run_gate(thresholds: dict | None = None, strict: bool = False) -> GateReport:
    cfg = thresholds or load_thresholds()
    report = GateReport(strict=strict)
    report.checks.extend(_check_reliability(cfg.get("reliability", {})))
    report.checks.extend(_check_telemetry_truthfulness(cfg.get("telemetry", {})))
    report.checks.extend(_check_retrieval(cfg.get("retrieval", {})))
    return report


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="YAPOC release gate")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="treat SKIPPED as failure")
    ap.add_argument("--thresholds", type=Path, default=None)
    args = ap.parse_args()

    report = run_gate(load_thresholds(args.thresholds), strict=args.strict)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for check in report.checks:
            print(check.line())
        print()
        if report.passed:
            print(f"GATE PASSED ({len(report.checks)} check(s), {len(report.skips)} skipped)")
        else:
            reason = f"{len(report.failures)} failure(s)"
            if report.strict and report.skips:
                reason += f", {len(report.skips)} skip(s) under --strict"
            print(f"GATE FAILED — {reason}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
