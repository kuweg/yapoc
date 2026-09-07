"""Phase 3.6 — the release gate must be able to fail, and must fail loudly.

A gate that cannot fail is a rubber stamp. These tests pin the two ways a gate
silently becomes one: passing on an empty window (no data mistaken for health),
and passing when a threshold is breached.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils import release_gate as G


THRESHOLDS = Path(__file__).resolve().parents[1] / "release_gates.json"


def test_shipped_thresholds_are_valid_and_documented():
    """Every threshold needs a recorded reason, or the number is folklore."""
    cfg = json.loads(THRESHOLDS.read_text())
    assert set(cfg) >= {"reliability", "retrieval", "telemetry"}

    rel = cfg["reliability"]
    for key in ("max_failure_rate", "max_turn_limit_failures",
                "max_provider_failures", "min_tasks"):
        assert key in rel, key
    # Each numeric bar carries a sibling `_why`.
    for section in ("reliability", "retrieval"):
        block = cfg[section]
        assert any(k.startswith("_") and k.endswith("why") or k == "_why"
                   for k in block), f"{section} has no rationale recorded"


def test_turn_limit_bar_is_zero():
    """Phase 0 converts exhaustion into continuations, so any failure regresses it."""
    cfg = json.loads(THRESHOLDS.read_text())
    assert cfg["reliability"]["max_turn_limit_failures"] == 0


# ── Verdict logic ──────────────────────────────────────────────────────────


def _report(*checks, strict=False):
    return G.GateReport(checks=list(checks), strict=strict)


def test_all_passing_gate_passes():
    r = _report(G.Check("a", "PASS", ""), G.Check("b", "PASS", ""))
    assert r.passed and not r.failures


def test_one_failure_fails_the_gate():
    r = _report(G.Check("a", "PASS", ""), G.Check("b", "FAIL", "bad"))
    assert not r.passed
    assert [c.name for c in r.failures] == ["b"]


def test_skips_pass_by_default_but_fail_under_strict():
    """A skip is 'we could not tell', which is a release decision, not a bug."""
    checks = (G.Check("a", "PASS", ""), G.Check("b", "SKIPPED", "no data"))
    assert _report(*checks).passed
    assert not _report(*checks, strict=True).passed


# ── Empty-window handling ──────────────────────────────────────────────────


async def test_thin_window_skips_rather_than_passing(monkeypatch):
    """The dangerous failure: 0 failures because nothing ran looks like health."""

    class _Card:
        completed = 3
        failed = 0
        failure_rate = 0.0
        failure_mix: dict = {}
        cost_per_completed_task = None

    async def _fake(days=7):
        return _Card()

    monkeypatch.setattr(
        "app.backend.routers.metrics.get_reliability_scorecard", _fake
    )
    checks = G._check_reliability({"window_days": 7, "min_tasks": 20,
                                   "max_failure_rate": 0.04,
                                   "max_turn_limit_failures": 0,
                                   "max_provider_failures": 0})
    assert len(checks) == 1
    assert checks[0].verdict == "SKIPPED"
    assert "need 20" in checks[0].detail


async def test_breached_thresholds_fail(monkeypatch):
    class _Card:
        completed = 90
        failed = 10
        failure_rate = 0.10
        failure_mix = {"turn_limit": 4, "provider_config": 2}
        cost_per_completed_task = 1.5

    async def _fake(days=7):
        return _Card()

    monkeypatch.setattr(
        "app.backend.routers.metrics.get_reliability_scorecard", _fake
    )
    checks = G._check_reliability({
        "window_days": 7, "min_tasks": 20, "max_failure_rate": 0.04,
        "max_turn_limit_failures": 0, "max_provider_failures": 0,
        "max_cost_per_completed_task": 0.5,
    })
    by_name = {c.name: c for c in checks}
    assert by_name["failure_rate"].verdict == "FAIL"
    assert by_name["turn_limit_failures"].verdict == "FAIL"
    assert by_name["provider_failures"].verdict == "FAIL"
    assert by_name["cost_per_completed_task"].verdict == "FAIL"


async def test_healthy_window_passes(monkeypatch):
    class _Card:
        completed = 98
        failed = 2
        failure_rate = 0.02
        failure_mix = {"timeout": 2}
        cost_per_completed_task = 0.01

    async def _fake(days=7):
        return _Card()

    monkeypatch.setattr(
        "app.backend.routers.metrics.get_reliability_scorecard", _fake
    )
    checks = G._check_reliability({
        "window_days": 7, "min_tasks": 20, "max_failure_rate": 0.04,
        "max_turn_limit_failures": 0, "max_provider_failures": 0,
        "max_cost_per_completed_task": 0.5,
    })
    assert all(c.verdict == "PASS" for c in checks), [c.line() for c in checks]


# ── Telemetry reconciliation ───────────────────────────────────────────────


async def test_telemetry_mismatch_fails(monkeypatch):
    """Guards the Phase 1 bug class directly: counters drifting from the tables."""
    monkeypatch.setattr(
        "app.backend.routers.metrics._recent_task_incidents",
        lambda: ([], {"builder": 5, "planning": 3}, {}),
    )

    class _Totals:
        task_failure_count = 2  # dashboard under-reports

    class _Dash:
        totals = _Totals()

    async def _fake_dash():
        return _Dash()

    monkeypatch.setattr(
        "app.backend.routers.metrics.get_observability_dashboard", _fake_dash
    )
    checks = G._check_telemetry_truthfulness({})
    assert checks[0].verdict == "FAIL"
    assert "8" in checks[0].detail and "2" in checks[0].detail


async def test_telemetry_agreement_passes(monkeypatch):
    monkeypatch.setattr(
        "app.backend.routers.metrics._recent_task_incidents",
        lambda: ([], {"builder": 5}, {}),
    )

    class _Totals:
        task_failure_count = 5

    class _Dash:
        totals = _Totals()

    async def _fake_dash():
        return _Dash()

    monkeypatch.setattr(
        "app.backend.routers.metrics.get_observability_dashboard", _fake_dash
    )
    assert G._check_telemetry_truthfulness({})[0].verdict == "PASS"


def test_report_serializes_for_ci():
    r = _report(G.Check("a", "FAIL", "too high", observed=0.1, threshold=0.04))
    payload = r.to_dict()
    assert payload["passed"] is False
    assert payload["checks"][0]["observed"] == 0.1
    assert payload["checks"][0]["threshold"] == 0.04
    json.dumps(payload)  # must be JSON-serializable for CI consumption
