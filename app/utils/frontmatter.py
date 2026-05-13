"""Shared frontmatter parser for TASK.MD / agent markdown files.

The same `---\n<key>: <value>\n---` block was being parsed by four separate
implementations (BaseAgent, AgentRunner, delegation tools, stale-task router)
with subtly different return types and regex variants. This module is the
single source of truth.

Format:

    ---
    status: pending
    assigned_by: master
    task_id: abc-123
    ---

    <body>
"""
from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse the frontmatter block at the top of ``content``.

    Returns ``(fields, body)``. If no frontmatter is present, ``fields`` is
    empty and ``body`` is the original content. Values containing colons are
    preserved by splitting on the first colon only.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields, content[m.end():]


def parse_frontmatter_fields(content: str) -> dict[str, str]:
    """Return only the frontmatter fields, discarding the body."""
    fields, _ = parse_frontmatter(content)
    return fields
