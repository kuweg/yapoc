"""Phase 3.3 — the scenario suite must actually exercise things, and must not
spend money by accident.

Every other measurement in this roadmap reads what the system already did.
Scenarios ask it to do something and check the result, which is the only way to
catch "still finishes, now does the wrong thing" — invisible to a failure rate.
"""

from __future__ import annotations

import pytest

from app.utils import scenario_suite as S


def test_offline_scenarios_all_pass_today():
    """The published baseline. A failure here is a real regression."""
    report = S.run_offline()
    assert not report.failures, [r.line() for r in report.failures]
    assert len(report.results) == len(S.OFFLINE_SCENARIOS)


def test_offline_scenarios_cover_every_category():
    """A suite that only tests one dimension gives false confidence."""
    categories = {sc.category for sc in S.OFFLINE_SCENARIOS}
    assert {"security", "config", "recovery", "research"} <= categories


def test_offline_scenarios_make_no_model_calls(monkeypatch):
    """`offline` has to mean offline, or CI starts costing money."""
    def _boom(*a, **k):
        raise AssertionError("offline scenario attempted a network/model call")

    import httpx

    monkeypatch.setattr(httpx, "post", _boom)
    monkeypatch.setattr(httpx, "get", _boom)
    report = S.run_offline()
    assert not report.failures


def test_live_scenarios_refuse_without_explicit_confirmation():
    """The guard that stops a scheduler spending the user's money by mistake."""
    report = S.run_live(confirm_spend=False)
    assert all(r.skipped for r in report.results)
    assert all("confirm_spend" in r.detail for r in report.results)
    assert not report.failures, "a refused live run must not read as a failure"


def test_live_run_is_not_the_default(monkeypatch):
    """Calling run_live() with no arguments must not dispatch anything."""
    import httpx

    def _boom(*a, **k):
        raise AssertionError("run_live dispatched a task without confirmation")

    monkeypatch.setattr(httpx, "post", _boom)
    report = S.run_live()
    assert all(r.skipped for r in report.results)


def test_a_broken_scenario_fails_rather_than_crashing_the_suite():
    """One bad scenario must not take the whole run down."""
    def _raises():
        raise RuntimeError("boom")

    bad = S.Scenario("broken/x", "offline", "security", "raises", check=_raises)
    report = S.run_offline((bad,))
    assert len(report.failures) == 1
    assert "boom" in report.failures[0].detail


def test_security_scenario_detects_a_reopened_bypass(monkeypatch):
    """The suite has to be able to fail — verified by breaking the gate."""
    monkeypatch.setattr(
        "app.utils.tools.security_policy.hardcoded_check",
        lambda tool, params, caller="": ("allow", "sabotaged"),
    )
    passed, detail = S._sc_destructive_shell_refused()
    assert not passed
    assert "not denied" in detail


def test_false_positive_scenario_detects_over_blocking(monkeypatch):
    """Safety that blocks real work gets switched off, so it is not safety."""
    monkeypatch.setattr(
        "app.utils.tools.security_policy.hardcoded_check",
        lambda tool, params, caller="": ("deny", "over-eager"),
    )
    passed, detail = S._sc_legitimate_work_not_blocked()
    assert not passed
    assert "denied" in detail


def test_report_summary_counts_skips_separately():
    report = S.SuiteReport(results=[
        S.ScenarioResult("a", True, ""),
        S.ScenarioResult("b", False, "nope"),
        S.ScenarioResult("c", False, "skipped", skipped=True),
    ])
    assert len(report.failures) == 1
    assert "1/2 passed" in report.summary()
    assert "1 skipped" in report.summary()
