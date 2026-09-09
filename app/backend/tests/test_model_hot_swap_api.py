"""API surface for the model/provider hot swap.

The endpoints must persist the new binding *and* broadcast it: every agent
title in the UI renders the live adapter/model, and the chat header's master
label is fetched only on mount, so without the broadcast it would keep naming
the old provider indefinitely.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app

client = TestClient(app)


@pytest.fixture
def captured_broadcasts(monkeypatch):
    """Record what would have gone out over the WebSocket."""
    sent: list[tuple[str, dict]] = []

    async def _push(event_type, payload):
        sent.append((event_type, payload))

    from app.backend.websocket import ws_manager
    monkeypatch.setattr(ws_manager, "push_event", _push)
    return sent


@pytest.fixture
def no_write(monkeypatch):
    """Stub the persistence layer so tests never touch the real settings file."""
    calls: list[tuple] = []

    def _swap_agent(name, adapter, model, **kw):
        calls.append(("agent", name, adapter, model))
        return {"adapter": adapter, "model": model}

    def _swap_provider(adapter, model, names=None):
        targets = names or ["master", "builder"]
        calls.append(("provider", tuple(targets), adapter, model))
        return {n: {"adapter": adapter, "model": model} for n in targets}

    monkeypatch.setattr("app.backend.routers.models._agent_settings.swap_agent_model", _swap_agent)
    monkeypatch.setattr("app.backend.routers.models._agent_settings.swap_provider", _swap_provider)
    monkeypatch.setattr("app.backend.routers.models._sync_config_yaml", lambda *a: None)
    return calls


def test_swapping_one_agent_persists_and_broadcasts(no_write, captured_broadcasts):
    resp = client.put(
        "/models/agents/master/config",
        json={"adapter": "openai", "model": "gpt-4o-mini"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok", "name": "master", "agent": "master",
        "adapter": "openai", "model": "gpt-4o-mini",
    }
    assert no_write == [("agent", "master", "openai", "gpt-4o-mini")]
    assert captured_broadcasts == [
        ("model_changed", {"changes": [
            {"agent": "master", "adapter": "openai", "model": "gpt-4o-mini"},
        ]}),
    ]


def test_unknown_agent_is_404(no_write, captured_broadcasts):
    resp = client.put(
        "/models/agents/does-not-exist/config",
        json={"adapter": "openai", "model": "gpt-4o-mini"},
    )

    assert resp.status_code == 404
    assert no_write == []
    assert captured_broadcasts == []


def test_invalid_binding_is_400_and_broadcasts_nothing(captured_broadcasts, monkeypatch):
    """A rejected swap must not tell the UI that anything changed."""
    def _boom(*a, **kw):
        raise ValueError("Unknown adapter 'nope'")

    monkeypatch.setattr("app.backend.routers.models._agent_settings.swap_agent_model", _boom)

    resp = client.put(
        "/models/agents/master/config",
        json={"adapter": "nope", "model": "gpt-4o-mini"},
    )

    assert resp.status_code == 400
    assert "Unknown adapter" in resp.json()["detail"]
    assert captured_broadcasts == []


def test_fleet_swap_broadcasts_one_frame_for_all_agents(no_write, captured_broadcasts):
    resp = client.post(
        "/models/hot-swap",
        json={"adapter": "openai", "model": "gpt-4o-mini"},
    )

    assert resp.status_code == 200
    assert {c["agent"] for c in resp.json()["swapped"]} == {"master", "builder"}
    # One frame, not one per agent — the UI patches every title in a single update.
    assert len(captured_broadcasts) == 1
    event_type, payload = captured_broadcasts[0]
    assert event_type == "model_changed"
    assert len(payload["changes"]) == 2


def test_fleet_swap_can_target_a_subset(no_write, captured_broadcasts):
    resp = client.post(
        "/models/hot-swap",
        json={"adapter": "openai", "model": "gpt-4o-mini", "agents": ["master"]},
    )

    assert resp.status_code == 200
    assert [c["agent"] for c in resp.json()["swapped"]] == ["master"]
    assert no_write == [("provider", ("master",), "openai", "gpt-4o-mini")]


def test_fleet_swap_rejects_an_unknown_agent_before_writing(no_write, captured_broadcasts):
    resp = client.post(
        "/models/hot-swap",
        json={"adapter": "openai", "model": "gpt-4o-mini", "agents": ["master", "ghost"]},
    )

    assert resp.status_code == 404
    assert no_write == []
    assert captured_broadcasts == []


def test_a_failed_broadcast_does_not_fail_the_swap(no_write, monkeypatch):
    """The swap is already persisted; pollers will catch up on their own."""
    async def _explode(*a, **kw):
        raise RuntimeError("no clients")

    from app.backend.websocket import ws_manager
    monkeypatch.setattr(ws_manager, "push_event", _explode)

    resp = client.put(
        "/models/agents/master/config",
        json={"adapter": "openai", "model": "gpt-4o-mini"},
    )

    assert resp.status_code == 200
    assert no_write == [("agent", "master", "openai", "gpt-4o-mini")]
