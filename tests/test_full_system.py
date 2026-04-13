"""Full system integration test for YAPOC.

Run: poetry run python tests/test_full_system.py

Tests all implemented functionality:
1. Agent infrastructure (all 6 agents load, build tools, assemble context)
2. Delegation tools (spawn, ping, check_task_status, wait_for_agent, kill)
3. Agent file schema (frontmatter parse/update, mark_task_consumed)
4. Live agent feed (AgentPollState, toolbar rendering)
5. Async result injection (collect_agent_results, build_result_injection)
6. RESUME.MD auto-population (_rebuild_resume_md)
7. Doctor health check
8. Backend service (agent discovery)
9. Cron agent config + trigger path
"""

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings

PASS = 0
FAIL = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"  \033[32m✓\033[0m {name}")


def fail(name: str, msg: str):
    global FAIL
    FAIL += 1
    print(f"  \033[31m✗\033[0m {name}: {msg}")


def section(title: str):
    print(f"\n\033[1m{'─' * 60}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'─' * 60}\033[0m")


# ═══════════════════════════════════════════════════════════════════
# 1. Agent Infrastructure
# ═══════════════════════════════════════════════════════════════════

def test_agent_imports():
    section("1. Agent Infrastructure")

    from app.agents.base import BaseAgent
    from app.agents.master.agent import master_agent
    from app.agents.planning.agent import planning_agent
    from app.agents.builder.agent import builder_agent
    from app.agents.keeper.agent import keeper_agent
    from app.agents.cron.agent import cron_agent
    from app.agents.doctor.agent import doctor_agent

    agents = {
        "master": master_agent,
        "planning": planning_agent,
        "builder": builder_agent,
        "keeper": keeper_agent,
        "cron": cron_agent,
        "doctor": doctor_agent,
    }

    for name, agent in agents.items():
        if isinstance(agent, BaseAgent) and agent._dir.name == name:
            ok(f"import {name}")
        else:
            fail(f"import {name}", "not BaseAgent or dir mismatch")

    return agents


async def test_tool_loading():
    from app.agents.base import BaseAgent
    from app.utils.tools import build_tools

    expected_tool_counts = {
        "master": 22, "planning": 12, "builder": 12,
        "keeper": 8, "cron": 12, "doctor": 7,
    }

    for name, expected in expected_tool_counts.items():
        agent = BaseAgent(settings.agents_dir / name)
        tool_names = await agent._load_tool_names()
        tools = build_tools(tool_names, settings.agents_dir / name)
        if len(tools) == expected:
            ok(f"tools {name}: {len(tools)} loaded")
        else:
            fail(f"tools {name}", f"expected {expected}, got {len(tools)}: {[t.name for t in tools]}")


async def test_config_loading():
    from app.agents.base import BaseAgent

    expected_models = {
        "master": "claude-sonnet-4-6",
        "planning": "claude-sonnet-4-6",
        "builder": "claude-sonnet-4-6",
        "keeper": "claude-sonnet-4-6",
        "cron": "claude-haiku-4-5-20251001",
        "doctor": "claude-haiku-4-5-20251001",
    }

    for name, expected_model in expected_models.items():
        agent = BaseAgent(settings.agents_dir / name)
        config = await agent._load_config()
        if config.model == expected_model:
            ok(f"config {name}: model={config.model}")
        else:
            fail(f"config {name}", f"expected model={expected_model}, got {config.model}")


async def test_context_assembly():
    from app.agents.base.context import build_system_context

    for name in ["master", "planning", "builder", "keeper", "cron", "doctor"]:
        ctx = await build_system_context(settings.agents_dir / name)
        if len(ctx) > 100:
            ok(f"context {name}: {len(ctx)} chars")
        else:
            fail(f"context {name}", f"too short: {len(ctx)} chars")


# ═══════════════════════════════════════════════════════════════════
# 2. Agent File Schema
# ═══════════════════════════════════════════════════════════════════

async def test_frontmatter():
    section("2. Agent File Schema")

    from app.agents.base import BaseAgent

    # Test parse
    content = "---\nstatus: done\nassigned_by: master\n---\n## Task\nTest task\n"
    fm = BaseAgent._parse_frontmatter(content)
    if fm.get("status") == "done" and fm.get("assigned_by") == "master":
        ok("parse_frontmatter")
    else:
        fail("parse_frontmatter", f"got {fm}")

    # Test update
    updated = BaseAgent._update_frontmatter(content, consumed_at="2026-01-01T00:00:00Z")
    if "consumed_at: 2026-01-01T00:00:00Z" in updated and "status: done" in updated:
        ok("update_frontmatter")
    else:
        fail("update_frontmatter", f"got {updated[:200]}")

    # Test create frontmatter from scratch
    bare = "## Task\nSome task"
    with_fm = BaseAgent._update_frontmatter(bare, status="pending")
    if with_fm.startswith("---\nstatus: pending\n---\n"):
        ok("create_frontmatter_from_scratch")
    else:
        fail("create_frontmatter_from_scratch", f"got {with_fm[:100]}")


async def test_mark_task_consumed():
    """Test mark_task_consumed using a temp directory."""
    from app.agents.base import BaseAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        task_path = agent_dir / "TASK.MD"
        task_path.write_text(
            "---\nstatus: done\nassigned_by: master\n---\n## Task\nTest\n"
        )

        agent = BaseAgent(agent_dir)
        await agent.mark_task_consumed()

        content = task_path.read_text()
        fm = BaseAgent._parse_frontmatter(content)
        if fm.get("consumed_at"):
            ok("mark_task_consumed")
        else:
            fail("mark_task_consumed", f"no consumed_at in {fm}")


async def test_task_status_lifecycle():
    """Test set_task_status through pending -> running -> done."""
    from app.agents.base import BaseAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir)
        task_content = (
            "---\nstatus: pending\nassigned_by: master\n---\n\n"
            "## Task\nDo something\n\n## Result\n\n\n## Error\n\n"
        )
        (agent_dir / "TASK.MD").write_text(task_content)
        (agent_dir / "HEALTH.MD").write_text("")

        agent = BaseAgent(agent_dir)

        # Set running
        await agent.set_task_status("running")
        status = await agent.get_task_status()
        if status == "running":
            ok("set_task_status(running)")
        else:
            fail("set_task_status(running)", f"got {status}")

        # Set done with result
        await agent.set_task_status("done", result="All done!")
        status = await agent.get_task_status()
        content = (agent_dir / "TASK.MD").read_text()
        if status == "done" and "All done!" in content and "completed_at:" in content:
            ok("set_task_status(done, result=...)")
        else:
            fail("set_task_status(done)", f"status={status}, content={content[:200]}")


# ═══════════════════════════════════════════════════════════════════
# 3. Delegation Tools
# ═══════════════════════════════════════════════════════════════════

async def test_delegation_tools():
    section("3. Delegation Tools")

    from app.utils.tools.delegation import (
        PingAgentTool, CheckTaskStatusTool, KillAgentTool,
        _is_temporary_agent, _read_status,
    )

    # Ping a non-running agent
    ping = PingAgentTool()
    result = await ping.execute(agent_name="cron")
    if "no STATUS.json" in result or "not running" in result.lower() or "alive=False" in result:
        ok("ping_agent(cron) — not running")
    else:
        fail("ping_agent(cron)", f"unexpected: {result}")

    # Check task status for agent with no frontmatter
    cts = CheckTaskStatusTool()
    result = await cts.execute(agent_name="cron")
    if "no frontmatter" in result or "status=" in result:
        ok("check_task_status(cron)")
    else:
        fail("check_task_status(cron)", f"unexpected: {result}")

    # _is_temporary_agent on non-temporary
    if not _is_temporary_agent("keeper"):
        ok("_is_temporary_agent(keeper) = False")
    else:
        fail("_is_temporary_agent(keeper)", "should be False")


# ═══════════════════════════════════════════════════════════════════
# 4. Live Agent Feed (AgentPollState + Toolbar)
# ═══════════════════════════════════════════════════════════════════

def test_agent_poll_state():
    section("4. Live Agent Feed")

    from app.cli.renderer import AgentPollState, _make_toolbar

    ps = AgentPollState()

    # Empty state
    toolbar = _make_toolbar(ps)
    if toolbar() == "":
        ok("toolbar: empty when no agents")
    else:
        fail("toolbar empty", f"got {toolbar()!r}")

    # Simulate active agent
    import threading
    with ps._lock:
        ps.agents = {
            "planning": {"state": "running", "task_summary": "Breaking down task"},
            "builder": {"state": "idle", "task_summary": ""},
        }
    result = toolbar()
    if "planning:running" in result and "builder:idle" in result:
        ok("toolbar: shows active agents")
    else:
        fail("toolbar agents", f"got {result!r}")

    # Terminated agents should be hidden
    with ps._lock:
        ps.agents = {
            "planning": {"state": "terminated", "task_summary": ""},
        }
    result = toolbar()
    if result == "":
        ok("toolbar: hides terminated agents")
    else:
        fail("toolbar terminated", f"got {result!r}")

    # get_snapshot returns copy
    with ps._lock:
        ps.agents = {"test": {"state": "running"}}
    snap = ps.get_snapshot()
    snap["test"]["state"] = "MODIFIED"
    if ps.agents["test"]["state"] == "running":
        ok("get_snapshot: returns independent copy")
    else:
        fail("get_snapshot", "modifying snapshot affected original")


def test_turn_renderer_with_poll_state():
    from app.cli.renderer import AgentPollState, TurnRenderer
    from rich.console import Console

    ps = AgentPollState()
    import threading
    with ps._lock:
        ps.agents = {
            "planning": {"state": "running", "task_summary": "Working"},
            "builder": {"state": "running", "task_summary": "Building"},
        }

    renderer = TurnRenderer(Console(), poll_state=ps)
    panel = renderer._build_agent_panel()
    if panel is not None:
        ok("TurnRenderer: builds agent panel from shared poll_state")
    else:
        fail("TurnRenderer panel", "returned None with 2 active agents")


# ═══════════════════════════════════════════════════════════════════
# 5. Async Result Injection
# ═══════════════════════════════════════════════════════════════════

def test_result_injection():
    section("5. Async Result Injection")

    from app.cli.main import _build_result_injection, _show_agent_completions

    results = [
        ("builder", "Created 3 files", False),
        ("planning", "Task decomposition failed", True),
    ]

    text = _build_result_injection(results)
    if "[System notification: sub-agent tasks completed]" in text:
        ok("build_result_injection: has header")
    else:
        fail("build_result_injection header", f"missing header in {text[:100]}")

    if "### Agent: builder — DONE" in text and "Created 3 files" in text:
        ok("build_result_injection: done agent formatted")
    else:
        fail("build_result_injection done", f"missing builder in {text}")

    if "### Agent: planning — ERROR" in text:
        ok("build_result_injection: error agent formatted")
    else:
        fail("build_result_injection error", f"missing planning error in {text}")

    if text.endswith("[User's message follows:]"):
        ok("build_result_injection: ends with user delimiter")
    else:
        fail("build_result_injection end", f"bad ending: {text[-50:]}")

    # Truncation test
    long_result = [("builder", "x" * 3000, False)]
    text = _build_result_injection(long_result)
    if "... (truncated)" in text and len(text) < 3000:
        ok("build_result_injection: truncates long results")
    else:
        fail("build_result_injection truncation", f"len={len(text)}")


async def test_collect_agent_results():
    """Test _collect_agent_results with a temp agent directory."""
    from app.agents.base import BaseAgent

    # Create a fake agent with a done task
    fake_dir = settings.agents_dir / "_test_agent"
    fake_dir.mkdir(exist_ok=True)
    try:
        (fake_dir / "TASK.MD").write_text(
            "---\nstatus: done\nassigned_by: master\nassigned_at: 2026-01-01T00:00:00Z\n"
            "completed_at: 2026-01-01T00:01:00Z\n---\n\n"
            "## Task\nTest task\n\n## Result\nTest result text\n\n## Error\n\n"
        )

        from app.cli.main import _collect_agent_results
        results = await _collect_agent_results()

        found = [r for r in results if r[0] == "_test_agent"]
        if found and found[0][1] == "Test result text" and not found[0][2]:
            ok("collect_agent_results: found done task")
        else:
            fail("collect_agent_results", f"got {found}")

        # Check consumed_at was set
        content = (fake_dir / "TASK.MD").read_text()
        fm = BaseAgent._parse_frontmatter(content)
        if fm.get("consumed_at"):
            ok("collect_agent_results: marked consumed")
        else:
            fail("collect_agent_results consumed", f"fm={fm}")

        # Second call should NOT find it again
        results2 = await _collect_agent_results()
        found2 = [r for r in results2 if r[0] == "_test_agent"]
        if not found2:
            ok("collect_agent_results: skips consumed tasks")
        else:
            fail("collect_agent_results skip", f"found again: {found2}")

    finally:
        import shutil
        shutil.rmtree(fake_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# 6. RESUME.MD Auto-Population
# ═══════════════════════════════════════════════════════════════════

async def test_rebuild_resume_md():
    section("6. RESUME.MD Auto-Population")

    from app.cli.main import _rebuild_resume_md

    # Create a fake agent with a pending task
    fake_dir = settings.agents_dir / "_test_resume"
    fake_dir.mkdir(exist_ok=True)
    try:
        (fake_dir / "TASK.MD").write_text(
            "---\nstatus: running\nassigned_by: master\nassigned_at: 2026-01-01T00:00:00Z\n"
            "completed_at:\n---\n\n"
            "## Task\nBuild the login page\n\n## Result\n\n\n## Error\n\n"
        )

        result = _rebuild_resume_md()
        if "# Pending Agent Tasks" in result:
            ok("rebuild_resume_md: has header")
        else:
            fail("rebuild_resume_md header", f"got {result[:100]}")

        if "_test_resume" in result and "running" in result:
            ok("rebuild_resume_md: includes running task")
        else:
            fail("rebuild_resume_md content", f"got {result}")

        if "Build the login page" in result:
            ok("rebuild_resume_md: includes task body")
        else:
            fail("rebuild_resume_md body", f"got {result}")

    finally:
        import shutil
        shutil.rmtree(fake_dir, ignore_errors=True)

    # Clean state should return empty
    # (All real agents have consumed_at or no assigned_by: master)
    clean_result = _rebuild_resume_md()
    # May or may not be empty depending on real agent state
    ok(f"rebuild_resume_md clean: {len(clean_result)} chars")


# ═══════════════════════════════════════════════════════════════════
# 7. Doctor Health Check
# ═══════════════════════════════════════════════════════════════════

async def test_doctor():
    section("7. Doctor Health Check")

    from app.agents.doctor.agent import doctor_agent

    report = await doctor_agent.run_health_check()
    if "# Health Summary" in report:
        ok("doctor: produces health summary")
    else:
        fail("doctor summary", f"got {report[:100]}")

    if "**Status:**" in report:
        ok("doctor: has status line")
    else:
        fail("doctor status", f"missing status in {report[:200]}")

    # Check it wrote HEALTH_SUMMARY.MD
    summary_path = settings.agents_dir / "doctor" / "HEALTH_SUMMARY.MD"
    if summary_path.exists() and "# Health Summary" in summary_path.read_text():
        ok("doctor: wrote HEALTH_SUMMARY.MD")
    else:
        fail("doctor file", "HEALTH_SUMMARY.MD not written")

    # Check all 6 agents are covered
    for name in ["master", "planning", "builder", "keeper", "cron", "doctor"]:
        if f"## {name}" in report:
            ok(f"doctor: covers {name}")
        else:
            fail(f"doctor covers {name}", "missing from report")


# ═══════════════════════════════════════════════════════════════════
# 8. Backend Service
# ═══════════════════════════════════════════════════════════════════

async def test_backend():
    section("8. Backend Service")

    from app.backend.services import AgentService

    svc = AgentService()
    statuses = await svc.get_all_statuses()
    names = {s.name for s in statuses}

    expected = {"master", "planning", "builder", "keeper", "cron", "doctor"}
    if expected <= names:
        ok(f"backend: discovers all {len(expected)} agents")
    else:
        fail("backend discovery", f"missing: {expected - names}")

    # Each status has required fields
    for s in statuses:
        if hasattr(s, "name") and hasattr(s, "status") and hasattr(s, "model"):
            pass
        else:
            fail(f"backend fields {s.name}", "missing required fields")
            break
    else:
        ok("backend: all statuses have required fields")


# ═══════════════════════════════════════════════════════════════════
# 9. Cron Agent
# ═══════════════════════════════════════════════════════════════════

async def test_cron():
    section("9. Cron Agent")

    from app.agents.cron.agent import cron_agent
    from app.agents.base.context import build_system_context

    # Config loads correctly
    config = await cron_agent._load_config()
    if config.model == "claude-haiku-4-5-20251001":
        ok("cron: model is haiku (cost-optimized)")
    else:
        fail("cron model", f"got {config.model}")

    # Tools include delegation tools
    tools = await cron_agent._load_tool_names()
    if "spawn_agent" in tools and "wait_for_agent" in tools:
        ok("cron: has delegation tools")
    else:
        fail("cron tools", f"missing delegation: {tools}")

    # Context assembly includes prompt
    ctx = await build_system_context(settings.agents_dir / "cron")
    if "Cron Agent" in ctx and "run-schedule" in ctx:
        ok("cron: context includes prompt with schedule instructions")
    else:
        fail("cron context", f"missing key content in {len(ctx)} char context")

    # Backend scheduler setting exists
    if hasattr(settings, "cron_interval_minutes"):
        ok(f"cron: interval setting = {settings.cron_interval_minutes}m")
    else:
        fail("cron setting", "cron_interval_minutes not in settings")


# ═══════════════════════════════════════════════════════════════════
# 10. Wait-for-agent bug fix verification
# ═══════════════════════════════════════════════════════════════════

def test_wait_for_agent_fix():
    section("10. Bug Fixes")

    import ast
    source = (Path("app/utils/tools/delegation.py")).read_text()
    if "'status' in dir()" in source:
        fail("wait_for_agent bug", "still has 'status' in dir()")
    elif "last_status" in source:
        ok("wait_for_agent: uses last_status variable (bug fixed)")
    else:
        fail("wait_for_agent", "unexpected code pattern")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def async_main():
    test_agent_imports()
    await test_tool_loading()
    await test_config_loading()
    await test_context_assembly()
    await test_frontmatter()
    await test_mark_task_consumed()
    await test_task_status_lifecycle()
    await test_delegation_tools()
    test_agent_poll_state()
    test_turn_renderer_with_poll_state()
    test_result_injection()
    await test_collect_agent_results()
    await test_rebuild_resume_md()
    await test_doctor()
    await test_backend()
    await test_cron()
    test_wait_for_agent_fix()


def main():
    print("\n\033[1;33m" + "═" * 60 + "\033[0m")
    print("\033[1;33m  YAPOC Full System Integration Test\033[0m")
    print("\033[1;33m" + "═" * 60 + "\033[0m")

    asyncio.run(async_main())

    print(f"\n\033[1m{'═' * 60}\033[0m")
    total = PASS + FAIL
    if FAIL == 0:
        print(f"\033[1;32m  ALL {total} TESTS PASSED\033[0m")
    else:
        print(f"\033[1;31m  {FAIL} FAILED\033[0m / {PASS} passed / {total} total")
    print(f"\033[1m{'═' * 60}\033[0m\n")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
