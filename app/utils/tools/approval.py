"""Autonomous approval policy engine.

Reads `autonomous_policy:` blocks from agent CONFIG.md files and determines
whether a CONFIRM-tier tool call should be auto-approved, denied, or queued
for human review when no interactive approval gate is available.

Usage:
    from app.utils.tools.approval import check_policy

    decision = check_policy("builder", "shell_exec", {"command": "poetry run pytest"})
    # -> "auto_approve" | "deny" | "queue"
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class ToolPolicy:
    """Policy rules for a single tool."""
    auto_approve: list[str] = field(default_factory=list)  # glob patterns
    deny: list[str] = field(default_factory=list)           # glob patterns
    default: str = "queue"  # "queue" | "auto_approve" | "deny"


@dataclass
class AutonomousPolicy:
    """Full autonomous policy for an agent."""
    tool_policies: dict[str, ToolPolicy] = field(default_factory=dict)
    default_action: str = "queue"


def parse_autonomous_policy(config_text: str) -> AutonomousPolicy:
    """Parse the autonomous_policy: block from CONFIG.md text.

    Expected format:
    ```
    autonomous_policy:
      shell_exec:
        auto_approve: ["poetry run pytest*", "ls *", "cat *"]
        deny: ["rm -rf *", "sudo *", "curl * | bash"]
        default: queue
      file_write:
        auto_approve: ["app/projects/*"]
        deny: ["app/config/*", "*.env"]
        default: queue
    ```
    """
    policy = AutonomousPolicy()

    # Find the autonomous_policy block
    match = re.search(r"^autonomous_policy:\s*\n((?:[ \t]+.+\n?)*)", config_text, re.MULTILINE)
    if not match:
        return policy

    block = match.group(1)

    # Detect base indent level (first non-empty line's indent)
    base_indent = 0
    for line in block.split("\n"):
        if line.strip():
            base_indent = len(line) - len(line.lstrip())
            break

    current_tool: str | None = None
    current_field: str | None = None

    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Tool name level (base indent, e.g. 2 spaces)
        if indent == base_indent and ":" in stripped and not stripped.startswith("-"):
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key in ("default", "default_action"):
                policy.default_action = val.strip('"').strip("'") or policy.default_action
            else:
                current_tool = key
                current_field = None
                if current_tool not in policy.tool_policies:
                    policy.tool_policies[current_tool] = ToolPolicy()
            continue

        # Field level (base + 2 or more)
        if current_tool is None:
            continue
        tp = policy.tool_policies[current_tool]

        if indent > base_indent and ":" in stripped and not stripped.startswith("-"):
            parts = stripped.split(":", 1)
            field_name = parts[0].strip()
            value = parts[1].strip()

            if field_name == "default":
                tp.default = value.strip('"').strip("'")
                current_field = None
            elif field_name in ("auto_approve", "deny"):
                current_field = field_name
                patterns = _parse_list_value(value)
                if patterns:
                    getattr(tp, field_name).extend(patterns)
            continue

        # List item (- "pattern")
        if stripped.startswith("-") and current_field and current_tool:
            pattern = stripped[1:].strip().strip('"').strip("'")
            if pattern:
                getattr(policy.tool_policies[current_tool], current_field).append(pattern)

    return policy


def _parse_list_value(value: str) -> list[str]:
    """Parse an inline list like '["pattern1", "pattern2"]'."""
    value = value.strip()
    if not value.startswith("["):
        return [value.strip('"').strip("'")] if value else []
    # Strip brackets and split
    inner = value.strip("[]")
    items = []
    for item in inner.split(","):
        item = item.strip().strip('"').strip("'")
        if item:
            items.append(item)
    return items


def _match_patterns(patterns: list[str], value: str) -> bool:
    """Check if value matches any of the glob patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(value, pattern):
            return True
    return False


def _extract_match_string(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extract the string to match against patterns based on tool type."""
    if tool_name == "shell_exec":
        return tool_input.get("command", "")
    if tool_name in ("file_write", "file_edit", "file_delete", "file_read"):
        return tool_input.get("path", tool_input.get("file_path", ""))
    if tool_name == "spawn_agent":
        return tool_input.get("agent_name", "") + " " + tool_input.get("task", "")
    if tool_name == "kill_agent":
        return tool_input.get("agent_name", "")
    # Generic: join all string values
    parts = [str(v) for v in tool_input.values() if isinstance(v, str)]
    return " ".join(parts)


def check_policy(
    agent_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    config_text: str = "",
) -> str:
    """Check the autonomous approval policy for a tool call.

    Returns: "auto_approve" | "deny" | "queue"
    """
    policy = parse_autonomous_policy(config_text)
    match_str = _extract_match_string(tool_name, tool_input)

    tp = policy.tool_policies.get(tool_name)
    if tp is None:
        # No specific policy for this tool — use global default
        return policy.default_action

    # Check deny first (deny takes precedence)
    if _match_patterns(tp.deny, match_str):
        logger.info(f"[APPROVAL] {agent_name}/{tool_name}: DENIED (pattern match) input={match_str[:100]}")
        return "deny"

    # Check auto_approve
    if _match_patterns(tp.auto_approve, match_str):
        logger.info(f"[APPROVAL] {agent_name}/{tool_name}: AUTO_APPROVE (pattern match) input={match_str[:100]}")
        return "auto_approve"

    # Fall through to tool default, then global default
    return tp.default or policy.default_action
