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


def _make_agent(root: Path, name: str = "testagent", **files: str) -> Path:
    """Lay out an agent the way the runtime does.

    PROMPT.MD / CONFIG.yaml live in the agent dir; MEMORY, NOTES, HEALTH and
    LEARNINGS live in the parallel memory tree that build_system_context reads
    (``agent_dir.parent.parent / "memory" / "agents" / agent_dir.name``).
    """
    agent_dir = root / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = agent_dir.parent.parent / "memory" / "agents" / name
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_files = {"MEMORY.MD", "NOTES.MD", "HEALTH.MD", "LEARNINGS.MD"}
    for fname, content in files.items():
        target = memory_dir if fname in memory_files else agent_dir
        (target / fname).write_text(content)
    return agent_dir


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
        lines = [f"[2026-04-{i:02d} 10:00] task {i}" for i in range(1, 21)]
        config_text = "runner:\n  context_memory_limit: 5\n"
        agent_dir = _make_agent(
            Path(tmpdir),
            **{
                "PROMPT.MD": "Agent prompt.",
                "MEMORY.MD": "\n".join(lines),
                "NOTES.MD": "",
                "HEALTH.MD": "",
                "CONFIG.yaml": config_text,
            },
        )

        ctx = _run(build_system_context(agent_dir, config_text=config_text))
        assert "task 20" in ctx
        assert "task 16" in ctx
        # "task 1\n" or end-of-line — task 1 should not appear as a standalone entry
        # (task 16-20 contain "task 1" as substring, so check for exact "task 1]" absence)
        assert "] task 1\n" not in ctx and "task 1|" not in ctx


def test_build_system_context_notes_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_text = "runner:\n  context_notes_limit: 100\n"
        agent_dir = _make_agent(
            Path(tmpdir),
            **{
                "PROMPT.MD": "Agent prompt.",
                "MEMORY.MD": "",
                "NOTES.MD": "A" * 5000,
                "HEALTH.MD": "",
                "CONFIG.yaml": config_text,
            },
        )

        ctx = _run(build_system_context(agent_dir, config_text=config_text))
        # The context no longer appends a "…truncated" marker, but the cap is
        # still applied — 5000 A's must not survive whole.
        assert "A" * 5000 not in ctx
        assert "A" * 100 in ctx


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
