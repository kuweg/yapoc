"""Phase 4B — the routing policy must actually reach master.

Phase 3.4 built a policy that compares agents on measured success and cost, and
nothing consulted it. A recommendation nobody sees is a dead-ended advisor.

It is injected as context, not as an override: master keeps the decision, and
the reasoning stays visible in the transcript. A statistic that silently
rewrites delegation is undebuggable when it misfires.
"""

from __future__ import annotations

from app.agents.master.agent import MasterAgent
from app.utils.routing_policy import AgentStats


def test_advisory_fires_for_concrete_work_with_history(monkeypatch):
    monkeypatch.setattr(
        "app.utils.routing_policy.agent_stats",
        lambda days=30, db=None: {
            "builder": AgentStats("builder", 236, 0.97, 0.0103, 37.0),
            "planning": AgentStats("planning", 80, 0.85, 0.0288, 84.0),
        },
    )
    out = MasterAgent._routing_advisory("create the file app/utils/x.py with a helper")
    assert "Routing advisory" in out
    assert "builder" in out
    assert "97%" in out
    # Master must be told it can disagree.
    assert "override" in out.lower()


def test_no_advisory_without_measured_history(monkeypatch):
    """Restating the existing default is noise that trains master to ignore it."""
    monkeypatch.setattr(
        "app.utils.routing_policy.agent_stats", lambda days=30, db=None: {}
    )
    assert MasterAgent._routing_advisory("create the file x.py") == ""


def test_no_advisory_for_single_owner_task_classes(monkeypatch):
    monkeypatch.setattr(
        "app.utils.routing_policy.agent_stats",
        lambda days=30, db=None: {"builder": AgentStats("builder", 236, 0.97, 0.01, 37.0)},
    )
    for prompt in ("research the best pdf library",
                   "figure out how we should approach caching",
                   "configure the api key"):
        assert MasterAgent._routing_advisory(prompt) == ""


def test_advisory_never_raises(monkeypatch):
    """A convenience must never cost the task."""
    def _boom(*a, **k):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr("app.utils.routing_policy.agent_stats", _boom)
    assert MasterAgent._routing_advisory("create the file x.py") == ""
    assert MasterAgent._routing_advisory("") == ""
    assert MasterAgent._routing_advisory(None) == ""


def test_advisory_is_wired_into_the_task_context():
    """The helper existing is not the same as master receiving it."""
    import inspect

    src = inspect.getsource(MasterAgent.handle_task_stream)
    assert "_routing_advisory" in src
    assert "routing_context" in src
    assert "combined_context" in src


def test_offline_scenarios_are_enforced_in_ci():
    """Phase 4B scheduled them; a `continue-on-error` would undo that."""
    import yaml

    workflow = yaml.safe_load(open(".github/workflows/tests.yml"))
    steps = workflow["jobs"]["release-gate"]["steps"]
    scenario = next(s for s in steps if s.get("name") == "Scenario suite (offline)")
    assert "scenario_suite --offline" in scenario["run"]
    assert not scenario.get("continue-on-error"), (
        "offline scenarios do not depend on production history — they either "
        "hold or they do not, so they should block"
    )


def test_scenario_suite_runs_on_a_schedule():
    """Two offline checks read LIVE state, which CI cannot see between pushes."""
    from app.utils.cron_parser import parse_schedule

    jobs = parse_schedule(open("app/agents/cron/NOTES.MD").read())
    job = next((j for j in jobs if j.get("id") == "scenario-suite"), None)
    assert job is not None, "scenario-suite cron entry missing"
    assert job.get("cron"), "no cron expression"
    assert "scenario_suite --offline" in job.get("task", "")
    # It must not tell an agent to go fix things on its own.
    assert "not attempt to fix" in job.get("task", "").lower()
