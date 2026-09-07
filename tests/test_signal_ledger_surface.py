"""Phase 3.2 — the evaluator's findings must be visible and current.

The ledger already tracked resolution correctly (34 signals, 31 resolved), but
two things kept it from being useful:

1. `update_ledger()` was only called from `propose_goals()`, which only runs
   when a human types `yapoc propose-goals`. Nothing refreshed it after an
   evaluator round, so it drifted to round 93 against a round-104 report.
2. Nothing surfaced per-signal detail — `ledger_snapshot()` returns aggregate
   counts only.

The visible cost: a signal reading "Observability error counters still blind to
task-level failures" was still listed as OPEN long after that bug was fixed,
because nothing had reconciled it.
"""

from __future__ import annotations

import json

import pytest

from app.backend.routers import metrics as M


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the ledger at a temp file and return a writer for it."""
    import app.utils.signal_ledger as sl

    path = tmp_path / "signal_ledger.json"
    monkeypatch.setattr(sl, "_LEDGER_PATH", path, raising=False)
    monkeypatch.setattr(sl, "_load_ledger", lambda: json.loads(path.read_text()) if path.exists() else {})

    def write(entries):
        path.write_text(json.dumps(entries))

    return write


def _entry(sid, title, status="open", rounds_open=1, last_round=100, impact="MEDIUM"):
    return {
        "signal_id": sid, "title": title, "impact": impact, "status": status,
        "rounds_open": rounds_open, "first_seen_round": last_round - rounds_open,
        "last_seen_round": last_round, "last_seen_ts": "2026-09-07 12:00",
    }


async def test_open_signals_are_surfaced(ledger, monkeypatch):
    ledger({
        "a": _entry("a", "Counters blind to task failures"),
        "b": _entry("b", "Fixed thing", status="resolved"),
    })
    monkeypatch.setattr(M, "_signal_scan_rounds", lambda: [100], raising=False)

    resp = await M.get_signal_ledger()
    assert resp.total == 2
    assert resp.open_count == 1
    assert resp.resolved_count == 1
    assert [s.title for s in resp.open_signals] == ["Counters blind to task failures"]


async def test_staleness_is_reported(ledger, monkeypatch):
    """The number that says "these findings are being judged against old data"."""
    ledger({"a": _entry("a", "Something", last_round=93)})

    class _F:
        round_number = 104

    monkeypatch.setattr("app.utils.signal_ledger.scan_findings", lambda: [_F()])
    resp = await M.get_signal_ledger()
    assert resp.ledger_round == 93
    assert resp.latest_report_round == 104
    assert resp.staleness_rounds == 11


async def test_staleness_is_never_negative(ledger, monkeypatch):
    """A ledger ahead of the report is not "negative staleness"."""
    ledger({"a": _entry("a", "Something", last_round=110)})

    class _F:
        round_number = 104

    monkeypatch.setattr("app.utils.signal_ledger.scan_findings", lambda: [_F()])
    resp = await M.get_signal_ledger()
    assert resp.staleness_rounds == 0


async def test_longest_open_signals_come_first(ledger, monkeypatch):
    ledger({
        "a": _entry("a", "Recent", rounds_open=1),
        "b": _entry("b", "Chronic", rounds_open=9),
        "c": _entry("c", "Middling", rounds_open=4),
    })
    monkeypatch.setattr("app.utils.signal_ledger.scan_findings", lambda: [])
    resp = await M.get_signal_ledger()
    assert [s.title for s in resp.open_signals] == ["Chronic", "Middling", "Recent"]


async def test_empty_and_corrupt_ledgers_do_not_break_the_endpoint(ledger, monkeypatch):
    monkeypatch.setattr("app.utils.signal_ledger.scan_findings", lambda: [])
    ledger({})
    resp = await M.get_signal_ledger()
    assert resp.total == 0 and resp.open_count == 0

    ledger({"junk": "not a dict"})
    resp = await M.get_signal_ledger()
    assert resp.total == 1 and resp.open_count == 0


def test_runner_refreshes_the_ledger_only_for_the_evaluator():
    """The hook must not fire for every agent — it is evaluator bookkeeping."""
    import inspect

    from app.agents.base import runner

    src = inspect.getsource(runner.AgentRunner._run_task)
    assert 'self._name == "evaluator"' in src
    assert "update_ledger" in src
    # It must be inside a guarded, non-fatal block.
    assert "signal ledger refresh failed" in src
