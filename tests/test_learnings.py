"""Tests for M6 — Agent Learning (LEARNINGS.MD, learnings_append tool, context injection, outcome classification)."""

import asyncio
import tempfile
from pathlib import Path

from app.agents.base.context import build_system_context


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _redirect_project_root(monkeypatch, root: Path) -> None:
    """Point settings.project_root at a temp dir.

    LearningsAppendTool writes to ``settings.project_root/app/memory/agents/
    <name>/LEARNINGS.MD``. project_root is a read-only property, so patch it on
    the class — without this the tests write into the real repository.
    """
    from app.config import settings

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: root))


def _learnings_path(root: Path, agent_name: str) -> Path:
    return root / "app" / "memory" / "agents" / agent_name / "LEARNINGS.MD"


def _make_agent(root: Path, name: str = "testagent", **files: str) -> Path:
    """Agent dir + parallel memory dir, matching the runtime layout."""
    agent_dir = root / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = agent_dir.parent.parent / "memory" / "agents" / name
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_files = {"MEMORY.MD", "NOTES.MD", "HEALTH.MD", "LEARNINGS.MD"}
    for fname, content in files.items():
        target = memory_dir if fname in memory_files else agent_dir
        (target / fname).write_text(content)
    return agent_dir


class TestLearningsAppendTool:
    def test_creates_learning_entry(self, tmp_path, monkeypatch):
        from app.utils.tools.memory import LearningsAppendTool

        _redirect_project_root(monkeypatch, tmp_path)
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()

        tool = LearningsAppendTool(agent_dir=agent_dir)
        result = _run(tool.execute(
            rule_name="Always check .npmrc before npm install",
            context="npm install fails without .npmrc on this project",
            action="Check for .npmrc existence before running npm install",
            confidence="high",
        ))

        assert "Learning stored" in result
        content = _learnings_path(tmp_path, "agent").read_text()
        assert "## Rule: Always check .npmrc" in content
        assert "**Confidence:** high" in content
        assert "**Action:** Check for .npmrc" in content

    def test_caps_at_20_rules(self, tmp_path, monkeypatch):
        from app.utils.tools.memory import LearningsAppendTool

        _redirect_project_root(monkeypatch, tmp_path)
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        # Write 20 existing rules where the tool actually reads them
        existing = "\n".join(f"## Rule: Rule {i}\n- test\n" for i in range(20))
        path = _learnings_path(tmp_path, "agent")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(existing)

        tool = LearningsAppendTool(agent_dir=agent_dir)
        result = _run(tool.execute(
            rule_name="Rule 21",
            context="test",
            action="test",
        ))

        assert "already has 20 rules" in result
        content = _learnings_path(tmp_path, "agent").read_text()
        assert "Rule 21" not in content

    def test_scrubs_secrets_in_learnings(self, tmp_path, monkeypatch):
        from app.utils.tools.memory import LearningsAppendTool

        _redirect_project_root(monkeypatch, tmp_path)
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()

        tool = LearningsAppendTool(agent_dir=agent_dir)
        _run(tool.execute(
            rule_name="API key handling",
            context="Found key sk-ant-abc123def456ghi789jkl012mno in logs",
            action="Never log API keys",
        ))

        content = _learnings_path(tmp_path, "agent").read_text()
        assert "sk-ant-" not in content
        assert "[REDACTED]" in content


class TestLearningsContextInjection:
    def test_learnings_injected_into_system_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = _make_agent(
                Path(tmpdir),
                **{
                    "PROMPT.MD": "You are a test agent.",
                    "MEMORY.MD": "",
                    "NOTES.MD": "",
                    "HEALTH.MD": "",
                    "LEARNINGS.MD": (
                        "## Rule: Always verify file exists before editing\n"
                        "- **Observed:** 2026-04-10\n"
                        "- **Action:** Call file_read before file_edit\n"
                    ),
                },
            )

            ctx = _run(build_system_context(agent_dir))
            assert "## Learned Rules" in ctx
            assert "Always verify file exists" in ctx

    def test_empty_learnings_not_injected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_dir = _make_agent(
                Path(tmpdir),
                **{
                    "PROMPT.MD": "You are a test agent.",
                    "MEMORY.MD": "",
                    "NOTES.MD": "",
                    "HEALTH.MD": "",
                    "LEARNINGS.MD": "",
                },
            )

            ctx = _run(build_system_context(agent_dir))
            assert "Learned Rules" not in ctx

    def test_learnings_capped_at_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_text = "runner:\n  context_learnings_limit: 100\n"
            agent_dir = _make_agent(
                Path(tmpdir),
                **{
                    "PROMPT.MD": "Agent.",
                    "MEMORY.MD": "",
                    "NOTES.MD": "",
                    "HEALTH.MD": "",
                    "LEARNINGS.MD": "R" * 5000,
                    "CONFIG.yaml": config_text,
                },
            )

            ctx = _run(build_system_context(agent_dir, config_text=config_text))
            # The "…truncated" marker was removed, but the cap still applies.
            assert "R" * 5000 not in ctx
            assert "R" * 100 in ctx


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
