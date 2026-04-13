"""Tests for app.agents.base.context — system context assembly."""

import asyncio
from pathlib import Path
import tempfile

from app.agents.base.context import build_system_context, _parse_runner_config


def test_parse_runner_config_basic():
    config = """runner:
  max_turns: 15
  task_timeout: 600
  context_memory_limit: 20
"""
    result = _parse_runner_config(config)
    assert result["max_turns"] == 15
    assert result["task_timeout"] == 600
    assert result["context_memory_limit"] == 20


def test_parse_runner_config_lifecycle():
    config = """lifecycle:
  temporary: true
runner:
  max_turns: 5
"""
    result = _parse_runner_config(config)
    assert result["lifecycle_temporary"] is True
    assert result["max_turns"] == 5


def test_parse_runner_config_empty():
    result = _parse_runner_config("")
    assert result == {}


def _run(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_build_system_context_with_prompt():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        (agent_dir / "PROMPT.MD").write_text("You are a test agent.")
        (agent_dir / "MEMORY.MD").write_text("")
        (agent_dir / "NOTES.MD").write_text("")
        (agent_dir / "HEALTH.MD").write_text("")

        ctx = _run(build_system_context(agent_dir))
        assert "You are a test agent." in ctx


def test_build_system_context_memory_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        (agent_dir / "PROMPT.MD").write_text("Agent prompt.")
        lines = [f"[2026-04-{i:02d} 10:00] task {i}" for i in range(1, 21)]
        (agent_dir / "MEMORY.MD").write_text("\n".join(lines))
        (agent_dir / "NOTES.MD").write_text("")
        (agent_dir / "HEALTH.MD").write_text("")
        config_text = "runner:\n  context_memory_limit: 5\n"
        (agent_dir / "CONFIG.md").write_text(config_text)

        ctx = _run(build_system_context(agent_dir, config_text=config_text))
        assert "task 20" in ctx
        assert "task 16" in ctx
        # "task 1\n" or end-of-line — task 1 should not appear as a standalone entry
        # (task 16-20 contain "task 1" as substring, so check for exact "task 1]" absence)
        assert "] task 1\n" not in ctx and "task 1|" not in ctx


def test_build_system_context_notes_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        (agent_dir / "PROMPT.MD").write_text("Agent prompt.")
        (agent_dir / "MEMORY.MD").write_text("")
        (agent_dir / "NOTES.MD").write_text("A" * 5000)
        (agent_dir / "HEALTH.MD").write_text("")
        config_text = "runner:\n  context_notes_limit: 100\n"
        (agent_dir / "CONFIG.md").write_text(config_text)

        ctx = _run(build_system_context(agent_dir, config_text=config_text))
        assert "notes truncated" in ctx


def test_build_system_context_preloaded_config():
    """config_text parameter should prevent re-reading CONFIG.md from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        (agent_dir / "PROMPT.MD").write_text("Test agent.")
        (agent_dir / "MEMORY.MD").write_text("")
        (agent_dir / "NOTES.MD").write_text("")
        (agent_dir / "HEALTH.MD").write_text("")
        config_text = "runner:\n  context_memory_limit: 3\n"

        ctx = _run(build_system_context(agent_dir, config_text=config_text))
        assert "Test agent." in ctx
