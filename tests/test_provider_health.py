"""Phase 4C — stop paying to relearn that a provider is out of credits.

Observed live: `OpenAI API error (429): You have no credits remaining`, with
OpenAI in all 14 agents' fallback chains. The chain failed over correctly but
did not *remember*, so every task paid a full round-trip to learn the same
thing again. Both the release gate and the evaluator found this independently.

An API-key check cannot catch it: the key is set and valid, the account simply
cannot pay. It has to be learned from responses.
"""

from __future__ import annotations

import time

import pytest

from app.utils.adapters import provider_health as ph


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "_state_path", lambda: tmp_path / "provider_health.json")
    yield


# ── Classification: the distinction that matters ───────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "OpenAI API error (429): You have no credits remaining. Add credits to continue",
        "Your credit balance is too low to access the API",
        "insufficient_quota: You exceeded your current quota",
        "billing_hard_limit_reached",
        "402 Payment Required",
    ],
)
def test_account_cannot_pay_is_exhausted(text):
    assert ph.classify_error(text) == "exhausted"


@pytest.mark.parametrize(
    "text",
    [
        "Rate limit reached for gpt-4, please retry after 20s",
        "429 Too Many Requests",
        "The engine is currently overloaded, please try again later",
        "server capacity exceeded",
    ],
)
def test_going_too_fast_is_transient_not_exhausted(text):
    """Benching a rate-limited provider turns a brief slowdown into an outage.

    Both arrive as HTTP 429. Conflating them would be worse than doing nothing.
    """
    assert ph.classify_error(text) == "transient"


def test_transient_wins_ties():
    """A message carrying both signals must not bench a working provider."""
    both = "429 rate limit reached; you exceeded your current quota"
    assert ph.classify_error(both) == "transient"


def test_unrelated_errors_are_neither():
    assert ph.classify_error("connection reset by peer") == "other"
    assert ph.classify_error("") == "other"
    assert ph.classify_error(None) == "other"


# ── Benching ───────────────────────────────────────────────────────────────


def test_exhausted_error_benches_the_provider():
    assert ph.record_error("openai", "You have no credits remaining") is True
    assert ph.is_exhausted("openai")
    assert not ph.is_exhausted("deepseek")


def test_transient_error_does_not_bench():
    assert ph.record_error("openai", "429 rate limit, please retry") is False
    assert not ph.is_exhausted("openai")


def test_cooldown_expires_so_a_topped_up_account_recovers():
    """Recovery must not require anyone remembering to clear state."""
    ph.record_error("openai", "no credits remaining")
    assert ph.is_exhausted("openai")
    later = time.time() + ph.DEFAULT_COOLDOWN_S + 1
    assert not ph.is_exhausted("openai", now=later)


def test_success_clears_the_bench_early():
    ph.record_error("openai", "no credits remaining")
    ph.record_success("openai")
    assert not ph.is_exhausted("openai")


def test_snapshot_reports_only_live_benches():
    ph.record_error("openai", "no credits remaining")
    snap = ph.snapshot()
    assert "openai" in snap
    assert snap["openai"]["seconds_remaining"] > 0
    assert "credits" in snap["openai"]["reason"]


def test_health_tracking_never_raises_on_a_broken_state_file(tmp_path, monkeypatch):
    """Health tracking must never be able to break a request."""
    bad = tmp_path / "corrupt.json"
    bad.write_text("{not json")
    monkeypatch.setattr(ph, "_state_path", lambda: bad)
    assert ph.is_exhausted("openai") is False
    assert ph.record_error("openai", "no credits remaining") in (True, False)
    ph.record_success("openai")
    assert isinstance(ph.snapshot(), dict)


# ── Chain ordering ─────────────────────────────────────────────────────────


def _chain(*adapters):
    from app.utils.adapters.base import AgentConfig
    from app.utils.adapters.fallback import FallbackAdapter

    return FallbackAdapter([
        AgentConfig(adapter=a, model=f"{a}-m", temperature=0.0, max_tokens=100)
        for a in adapters
    ])


def test_benched_providers_are_tried_last():
    ph.record_error("openai", "no credits remaining")
    order = _chain("openai", "deepseek", "google")._skip_order()
    assert order[0] != 0, "benched provider was still tried first"
    assert set(order) == {0, 1, 2}, "a chain entry was dropped entirely"
    assert order[-1] == 0


def test_healthy_chain_keeps_its_configured_order():
    """No reordering without a reason — priority is a deliberate config choice."""
    assert _chain("deepseek", "openai", "google")._skip_order() == [0, 1, 2]


def test_all_benched_still_attempts_everything():
    """Skipping every provider would fail with nothing tried, which is worse."""
    for a in ("openai", "deepseek", "google"):
        ph.record_error(a, "no credits remaining")
    order = _chain("openai", "deepseek", "google")._skip_order()
    assert sorted(order) == [0, 1, 2], "chain must still attempt when all are benched"


def test_note_outcome_benches_and_clears():
    chain = _chain("openai", "deepseek")
    chain._note_outcome(0, RuntimeError("You have no credits remaining"))
    assert ph.is_exhausted("openai")
    chain._note_outcome(0, None)
    assert not ph.is_exhausted("openai")


def test_note_outcome_ignores_transient_failures():
    chain = _chain("openai", "deepseek")
    chain._note_outcome(0, RuntimeError("429 rate limit reached"))
    assert not ph.is_exhausted("openai")
