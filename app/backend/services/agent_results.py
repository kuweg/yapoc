"""Collect completed background agent results and build injection prefix.

Both the CLI REPL and the HTTP streaming endpoint call these functions at the
start of each turn so that fire-and-forget sub-agent results surface
automatically — no ``wait_for_agent`` required.

Supports recursive multi-level delegation: when master spawns planning and
planning spawns builder, a single call to ``collect_agent_results()`` will
walk the full delegation tree and return a flat list of
``(agent_name, result_text, is_error, depth)`` tuples ordered depth-first.
"""
import re
from pathlib import Path

from app.agents.base import BaseAgent
from app.config import settings

# Cap per-agent result snippet in the injection block.
# Agents can write very long results; we don't want to blow up master's context.
_INJECTION_RESULT_CAP = 8_000


async def collect_agent_results(
    parent_agent: str = "master",
    depth: int = 0,
    visited: set[str] | None = None,
) -> list[tuple[str, str, bool, int]]:
    """Scan every agent TASK.MD for completed tasks assigned by ``parent_agent``.

    Recursively walks the delegation tree so that grandchildren (and deeper
    descendants) are collected in a single call.  Results are returned in
    depth-first order as ``(agent_name, result_text, is_error, depth)`` tuples.
    Tasks that are ``done`` or ``error`` and have not yet been consumed are
    marked consumed immediately so they are never returned twice.

    Args:
        parent_agent: The agent name to filter by (``assigned_by`` field in
            TASK.MD frontmatter).  Defaults to ``"master"`` for backward
            compatibility with existing callers.
        depth: Current recursion depth (0 = direct children of master).
            Used to track hierarchy level for notification formatting.
            Defaults to 0; callers should not normally set this.
        visited: Set of agent names already processed in this traversal.
            Prevents infinite loops in pathological delegation graphs.
            Defaults to None (a fresh empty set is created automatically).
    """
    if visited is None:
        visited = set()

    # Guard against cycles — mark parent as visited before descending.
    visited.add(parent_agent)

    results: list[tuple[str, str, bool, int]] = []

    try:
        agent_dirs = list(settings.agents_dir.iterdir())
    except OSError:
        return results

    for agent_dir in agent_dirs:
        if not agent_dir.is_dir() or agent_dir.name == parent_agent:
            continue
        task_path = agent_dir / "TASK.MD"
        if not task_path.exists():
            continue

        try:
            content = task_path.read_text(encoding="utf-8")
        except OSError:
            continue

        fm = BaseAgent._parse_frontmatter(content)
        if fm.get("assigned_by") != parent_agent:
            continue
        if fm.get("consumed_at"):
            continue
        status = fm.get("status", "")
        if status not in ("done", "error"):
            continue

        is_error = status == "error"
        section = "## Error" if is_error else "## Result"
        m = re.search(rf"{section}\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        result_text = m.group(1).strip() if m else "(no result)"

        agent = BaseAgent(agent_dir)
        await agent.mark_task_consumed()

        results.append((agent_dir.name, result_text, is_error, depth))

        # Recursively collect this child's own completed sub-tasks,
        # but only if we haven't visited this agent already (cycle guard).
        child_name = agent_dir.name
        if child_name not in visited:
            child_results = await collect_agent_results(
                parent_agent=child_name,
                depth=depth + 1,
                visited=visited,
            )
            results.extend(child_results)

    return results


def build_result_injection(results: list[tuple[str, str, bool, int]]) -> str:
    """Format collected results as a system-context notification block.

    The returned string is intended to be prepended as a system message so
    that the agent sees sub-task completions as background context rather
    than as part of the human turn.

    Hierarchy is reflected in Markdown heading levels:
    - Depth 0 (direct children of master):  ``### Agent: {name} — STATUS``
    - Depth 1 (grandchildren):              ``#### Sub-agent: {name} — STATUS``
    - Depth 2+ (deeper descendants):        ``##### Sub-sub-agent: {name} — STATUS``

    Args:
        results: List of ``(agent_name, result_text, is_error, depth)`` tuples
            as returned by ``collect_agent_results()``.  For backward
            compatibility, plain 3-tuples ``(agent_name, result_text, is_error)``
            are also accepted and treated as depth 0.
    """
    lines = ["[System notification: sub-agent tasks completed]", ""]

    for entry in results:
        # Support legacy 3-tuple callers (no depth field).
        if len(entry) == 3:
            agent_name, result_text, is_error = entry  # type: ignore[misc]
            depth = 0
        else:
            agent_name, result_text, is_error, depth = entry  # type: ignore[misc]

        label = "ERROR" if is_error else "DONE"
        if len(result_text) > _INJECTION_RESULT_CAP:
            result_text = result_text[:_INJECTION_RESULT_CAP] + "\n... (truncated)"

        if depth == 0:
            heading = f"### Agent: {agent_name} — {label}"
        elif depth == 1:
            heading = f"#### Sub-agent: {agent_name} — {label}"
        else:
            heading = f"{'#' * (depth + 3)} Sub-sub-agent: {agent_name} — {label}"

        lines.append(heading)
        lines.append(result_text)
        lines.append("")

    return "\n".join(lines).rstrip()
