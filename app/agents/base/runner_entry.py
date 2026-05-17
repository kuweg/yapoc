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
        asyncio.run(runner.run())
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
