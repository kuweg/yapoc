"""Subprocess entry point for agent runners.

Usage::

    python -m app.agents.base.runner_entry --agent planning

Or via the ``yapoc-agent`` script entry point::

    yapoc-agent --agent planning
"""

import argparse
import asyncio
import os
import sys
import traceback

from app.agents.base.runner import AgentRunner
from app.config import settings
from app.utils.crash import write_crash_report, count_crashes


async def _run_with_mcp(runner: AgentRunner) -> None:
    """Run the agent, connecting its declared MCP servers first.

    Each sub-agent process gets its OWN MCP connection for the servers it
    declares in ``mcp_servers`` in app/config/agent-settings.json. MCP is
    strictly optional here: any connect/register failure is logged (stderr)
    and the agent still runs - those servers' tools simply are not exposed.
    Servers are disconnected in a finally block once the runner exits.
    """
    host = None
    server_names: list[str] = []
    try:
        from app.utils.agent_settings import resolve_agent_mcp_servers
        from app.utils.mcp.config import load_mcp_config
        from app.utils.mcp.host import MCPHostManager
        from app.utils.mcp.registry import register_server_tools
        from app.utils.mcp.types import MCPConfig

        server_names = resolve_agent_mcp_servers(runner._name)
        all_cfg = load_mcp_config()
        filtered = MCPConfig(
            mcp_servers=[s for s in all_cfg.mcp_servers if s.name in server_names]
        )
        host = MCPHostManager()
        connected = await host.connect(filtered)
        if connected:
            await register_server_tools(host)
            print(f"[mcp] agent '{runner._name}' connected servers: {connected}")
        else:
            print(
                f"[mcp] agent '{runner._name}' no MCP servers connected for "
                f"{server_names}; running without MCP tools"
            )
        # NOTE: Tools stay registered in the shared TOOL_REGISTRY during
        # runner.run() — build_tools() reads from TOOL_REGISTRY at each
        # task-execution turn, so the wrappers must remain present for the
        # agent to call them. Only the host disconnect happens in the
        # finally block below.
    except Exception as exc:  # noqa: BLE001 - MCP failure is non-fatal
        traceback.print_exc(file=sys.stderr)
        print(
            f"[mcp] MCP setup failed for '{runner._name}': {exc}",
            file=sys.stderr,
        )
        host = None

    try:
        await runner.run()
    finally:
        if host is not None:
            try:
                await host.disconnect()
            except Exception:  # noqa: BLE001 - never let disconnect mask the result
                print(
                    f"[mcp] disconnect error for '{runner._name}':",
                    file=sys.stderr,
                )
                traceback.print_exc(file=sys.stderr)


def main() -> None:
    from app.backend.logging_config import setup_logging
    setup_logging()

    parser = argparse.ArgumentParser(description="Run a YAPOC agent process")
    parser.add_argument("--agent", required=True, help="Agent name (e.g. planning)")
    args = parser.parse_args()

    agent_dir = settings.agents_dir / args.agent
    if not agent_dir.is_dir():
        print(f"Error: agent directory not found: {agent_dir}", file=sys.stderr)
        sys.exit(1)

    crash_path = agent_dir / "CRASH.MD"

    try:
        runner = AgentRunner(args.agent)
        asyncio.run(_run_with_mcp(runner))
    except Exception:
        tb_str = traceback.format_exc()
        print(tb_str, file=sys.stderr)
        restart_count = count_crashes(crash_path)
        write_crash_report(
            crash_path,
            pid=os.getpid(),
            exit_code=1,
            entity_name=args.agent,
            restart_count=restart_count,
            traceback_str=tb_str,
        )
        sys.exit(1)
    else:
        # Normal completion (idle timeout, temporary task-complete, signal).
        # Force-exit so any lingering non-daemon threads spun up by third-
        # party SDKs cannot keep this subprocess alive after its work is
        # done. STATUS.json was already written to "terminated" inside
        # AgentRunner.run() and parent notifications already fired in
        # _shutdown(), so there is no state to flush.
        os._exit(0)


if __name__ == "__main__":
    main()
