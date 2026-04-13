"""Tool for reading agent output and crash logs."""

from pathlib import Path
from typing import Any

from app.config import settings

from . import BaseTool, RiskTier, truncate_tool_output

_VALID_LOG_FILES = {
    "OUTPUT.MD",
    "CRASH.MD",
    "SERVER_OUTPUT.MD",
    "SERVER_CRASH.MD",
    "HEALTH.MD",
    "HEALTH_SUMMARY.MD",
}


class ReadAgentLogsTool(BaseTool):
    name = "read_agent_logs"
    description = (
        "CRASH DIAGNOSIS ONLY. Reads the subprocess stdout/stderr capture "
        "(OUTPUT.MD / SERVER_OUTPUT.MD) and crash reports "
        "(CRASH.MD / SERVER_CRASH.MD) plus HEALTH.MD / HEALTH_SUMMARY.MD "
        "from an agent's directory. This does NOT contain the agent's "
        "LLM responses — for sub-agent output use `read_task_result` "
        "or `file_read app/agents/<name>/MEMORY.MD`. Use `tail_lines` "
        "to limit output."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent name (e.g. 'master', 'planning', 'doctor')",
            },
            "file": {
                "type": "string",
                "description": "Log file to read: OUTPUT.MD, CRASH.MD, SERVER_OUTPUT.MD, SERVER_CRASH.MD, HEALTH.MD, HEALTH_SUMMARY.MD",
            },
            "tail_lines": {
                "type": "integer",
                "description": "Only return the last N lines (default: 100)",
            },
        },
        "required": ["agent_name", "file"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        filename = params["file"]
        tail_lines = params.get("tail_lines", 100)

        if filename not in _VALID_LOG_FILES:
            return f"Error: invalid log file '{filename}'. Valid: {', '.join(sorted(_VALID_LOG_FILES))}"

        agent_dir = settings.agents_dir / agent_name
        if not agent_dir.is_dir():
            return f"Error: agent '{agent_name}' not found"

        path = agent_dir / filename
        if not path.exists():
            return f"[empty] {agent_name}/{filename} does not exist yet"

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error reading {filename}: {exc}"

        if not text.strip():
            return f"[empty] {agent_name}/{filename} is empty"

        lines = text.splitlines()
        if tail_lines and len(lines) > tail_lines:
            lines = lines[-tail_lines:]
            output = f"[showing last {tail_lines} of {len(text.splitlines())} lines]\n" + "\n".join(lines)
        else:
            output = "\n".join(lines)

        return truncate_tool_output(
            output,
            note=f"increase tail_lines or read file://app/agents/{agent_name}/{filename} for more",
        )
