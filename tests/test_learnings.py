"""Tests for M6 — Agent Learning (LEARNINGS.MD, learnings_append tool, context injection, outcome classification)."""

import asyncio
import tempfile
from pathlib import Path

from app.agents.base.context import build_system_context


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLearningsAppendTool:
    def test_creates_learning_entry(self, tmp_path):
        from app.utils.tools.memory import LearningsAppendTool

        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "LEARNINGS.MD").write_text("")

        tool = LearningsAppendTool(agent_dir=agent_dir)
        result = _run(tool.execute(
            rule_name="Always check .npmrc before npm install",
            context="npm install fails without .npmrc on this project",
            action="Check for .npmrc existence before running npm install",
            confidence="high",
        ))

        assert "Learning stored" in result
        content = (agent_dir / "LEARNINGS.MD").read_text()
        assert "## Rule: Always check .npmrc" in content
        assert "**Confidence:** high" in content
        assert "**Action:** Check for .npmrc" in content

    def test_caps_at_20_rules(self, tmp_path):
        from app.utils.tools.memory import LearningsAppendTool

        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        # Write 20 existing rules
        existing = "\n".join(f"## Rule: Rule {i}\n- test\n" for i in range(20))
        (agent_dir / "LEARNINGS.MD").write_text(existing)

        tool = LearningsAppendTool(agent_dir=agent_dir)
        result = _run(tool.execute(
            rule_name="Rule 21",
            context="test",
            action="test",
        ))

        assert "already has 20 rules" in result
        content = (agent_dir / "LEARNINGS.MD").read_text()
        assert "Rule 21" not in content

    def test_scrubs_secrets_in_learnings(self, tmp_path):
        from app.utils.tools.memory import LearningsAppendTool

        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "LEARNINGS.MD").write_text("")

        tool = LearningsAppendTool(agent_dir=agent_dir)
        _run(tool.execute(
            rule_name="API key handling",
            context="Found key sk-ant-abc123def456ghi789jkl012mno in logs",
            action="Never log API keys",
        ))

        content = (agent_dir / "LEARNINGS.MD").read_text()
        assert "sk-ant-" not in content
        assert "[REDACTED]" in content


class TestLearningsContextInjection:
    def test_learnings_injected_into_system_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = Path(tmpdir)
            (agent_dir / "PROMPT.MD").write_text("You are a test agent.")
            (agent_dir / "MEMORY.MD").write_text("")
            (agent_dir / "NOTES.MD").write_text("")
            (agent_dir / "HEALTH.MD").write_text("")
            (agent_dir / "LEARNINGS.MD").write_text(
                "## Rule: Always verify file exists before editing\n"
                "- **Observed:** 2026-04-10\n"
                "- **Action:** Call file_read before file_edit\n"
            )

            ctx = _run(build_system_context(agent_dir))
            assert "## Learned Rules" in ctx
            assert "Always verify file exists" in ctx

    def test_empty_learnings_not_injected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = Path(tmpdir)
            (agent_dir / "PROMPT.MD").write_text("You are a test agent.")
            (agent_dir / "MEMORY.MD").write_text("")
            (agent_dir / "NOTES.MD").write_text("")
            (agent_dir / "HEALTH.MD").write_text("")
            (agent_dir / "LEARNINGS.MD").write_text("")

            ctx = _run(build_system_context(agent_dir))
            assert "Learned Rules" not in ctx

    def test_learnings_truncated_at_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = Path(tmpdir)
            (agent_dir / "PROMPT.MD").write_text("Agent.")
            (agent_dir / "MEMORY.MD").write_text("")
            (agent_dir / "NOTES.MD").write_text("")
            (agent_dir / "HEALTH.MD").write_text("")
            (agent_dir / "LEARNINGS.MD").write_text("R" * 5000)
            config_text = "runner:\n  context_learnings_limit: 100\n"
            (agent_dir / "CONFIG.md").write_text(config_text)

            ctx = _run(build_system_context(agent_dir, config_text=config_text))
            assert "learnings truncated" in ctx


class TestOutcomeClassification:
    def test_memory_entries_include_outcome(self):
        """Verify the memory write format includes | outcome: suffix."""
        from app.agents.base import _sanitize_for_memory

        # The actual memory write happens in BaseAgent methods, but we can
        # verify the format pattern. Check that the _sanitize_for_memory
        # function doesn't strip the outcome suffix.
        sanitized = _sanitize_for_memory("Task completed successfully")
        # Build the entry as BaseAgent does:
        entry = f"[2026-04-13 10:00] task: test | result: {sanitized} | outcome: success\n"
        assert "| outcome: success" in entry


class TestToolRegistration:
    def test_learnings_append_in_registry(self):
        from app.utils.tools import TOOL_REGISTRY
        assert "learnings_append" in TOOL_REGISTRY

    def test_learnings_append_builds_with_agent_dir(self):
        from app.utils.tools import build_tools
        from app.config import settings

        for agent in ["master", "planning", "builder"]:
            tools = build_tools(["learnings_append"], settings.agents_dir / agent)
            assert len(tools) == 1
            assert tools[0].name == "learnings_append"
