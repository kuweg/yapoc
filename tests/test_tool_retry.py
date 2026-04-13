"""Tests for M4A — tool retry logic on transient errors."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from app.agents.base import BaseAgent
from app.utils.tools import BaseTool, RiskTier
from app.utils.adapters import ToolResult


@dataclass
class _FakeToolCall:
    id: str = "tc_1"
    name: str = "test_tool"
    input: dict = None

    def __post_init__(self):
        if self.input is None:
            self.input = {}


class _SucceedTool(BaseTool):
    name = "test_tool"
    description = "test"
    input_schema = {"type": "object", "properties": {}}
    risk_tier = RiskTier.AUTO

    async def execute(self, **params):
        return "ok"


class _TransientFailTool(BaseTool):
    """Fails with ConnectionError on first call, succeeds on second."""
    name = "test_tool"
    description = "test"
    input_schema = {"type": "object", "properties": {}}
    risk_tier = RiskTier.AUTO

    def __init__(self):
        self._calls = 0

    async def execute(self, **params):
        self._calls += 1
        if self._calls == 1:
            raise ConnectionError("Connection refused")
        return "recovered"


class _PermanentFailTool(BaseTool):
    """Always fails with ValueError (non-transient)."""
    name = "test_tool"
    description = "test"
    input_schema = {"type": "object", "properties": {}}
    risk_tier = RiskTier.AUTO

    async def execute(self, **params):
        raise ValueError("File not found: /nonexistent")


class _AlwaysTimeoutTool(BaseTool):
    """Always fails with TimeoutError."""
    name = "test_tool"
    description = "test"
    input_schema = {"type": "object", "properties": {}}
    risk_tier = RiskTier.AUTO

    def __init__(self):
        self._calls = 0

    async def execute(self, **params):
        self._calls += 1
        raise asyncio.TimeoutError("timed out")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_agent(tmp_path):
    agent_dir = tmp_path / "test_agent"
    agent_dir.mkdir()
    (agent_dir / "PROMPT.MD").write_text("test")
    (agent_dir / "MEMORY.MD").write_text("")
    (agent_dir / "HEALTH.MD").write_text("")
    (agent_dir / "NOTES.MD").write_text("")
    (agent_dir / "CONFIG.md").write_text("adapter: anthropic\nmodel: test\n")
    return BaseAgent(agent_dir)


def test_successful_tool_no_retry(tmp_path):
    agent = _make_agent(tmp_path)
    tool = _SucceedTool()
    tc = _FakeToolCall()
    result, done = _run(agent._execute_tool(tc, {"test_tool": tool}))
    assert not result.is_error
    assert result.content == "ok"


def test_transient_error_retried_and_recovers(tmp_path):
    agent = _make_agent(tmp_path)
    tool = _TransientFailTool()
    tc = _FakeToolCall()
    result, done = _run(agent._execute_tool(tc, {"test_tool": tool}))
    assert not result.is_error
    assert result.content == "recovered"
    assert tool._calls == 2  # first call failed, second succeeded


def test_permanent_error_not_retried(tmp_path):
    agent = _make_agent(tmp_path)
    tool = _PermanentFailTool()
    tc = _FakeToolCall()
    result, done = _run(agent._execute_tool(tc, {"test_tool": tool}))
    assert result.is_error
    assert "File not found" in result.content


def test_transient_error_exhausts_retries(tmp_path):
    agent = _make_agent(tmp_path)
    tool = _AlwaysTimeoutTool()
    tc = _FakeToolCall()
    result, done = _run(agent._execute_tool(tc, {"test_tool": tool}))
    assert result.is_error
    assert "timed out" in result.content
    assert tool._calls == 2  # original + 1 retry


def test_unknown_tool_not_retried(tmp_path):
    agent = _make_agent(tmp_path)
    tc = _FakeToolCall(name="nonexistent_tool")
    result, done = _run(agent._execute_tool(tc, {}))
    assert result.is_error
    assert "Unknown tool" in result.content
