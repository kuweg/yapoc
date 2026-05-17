"""Context assembly — build a full system prompt from agent files.

Reads PROMPT.MD, MEMORY.MD, NOTES.MD, and HEALTH.MD to give the agent
continuity across tasks without explicit notes_read calls.
"""

import re
from pathlib import Path

import aiofiles

from app.config import settings as _settings


def _parse_runner_config(config_text: str) -> dict[str, int | bool]:
    """Extract runner.* integer values and lifecycle.* booleans from CONFIG.yaml."""
    limits: dict[str, int | bool] = {}
    in_runner = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped == "runner:" or stripped.startswith("runner:"):
            in_runner = True
            continue
        if in_runner:
            m = re.match(r"\s+(\w+):\s*(\d+)", line)
            if m:
                limits[m.group(1)] = int(m.group(2))
            elif stripped and not stripped.startswith("#") and not line.startswith(" "):
                break  # next top-level key

    # Parse lifecycle: block (booleans)
    in_lifecycle = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped == "lifecycle:":
            in_lifecycle = True
            continue
        if in_lifecycle:
            m = re.match(r"\s+(\w+):\s*(true|false)", line, re.IGNORECASE)
            if m:
                limits[f"lifecycle_{m.group(1)}"] = m.group(2).lower() == "true"
            elif stripped and not stripped.startswith("#") and not line.startswith(" "):
                break
    return limits


async def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    async with aiofiles.open(path, encoding="utf-8") as f:
        return await f.read()


def _tail_lines(text: str, n: int, *, max_line_chars: int = 0) -> str:
    """Return the last N non-empty lines from text."""
    lines = [l for l in text.splitlines() if l.strip()]
    tail = lines[-n:]
    return "\n".join(tail)


# Matches a MEMORY.MD entry of the form:
#   [YYYY-MM-DD HH:MM] task: ... | result: ... | outcome: success
# The `| result: <...>` segment embeds the model's prior response text, which
# the model will imitate as a prose pattern if replayed verbatim. We strip
# the result payload before injection — keep the task descriptor + outcome
# so the model still knows what happened, just not WHAT prose to imitate.
_MEM_ENTRY_RE = re.compile(
    r"^(\[[^\]]+\]\s*task:\s*.+?)\s*\|\s*result:\s*.+?(\|\s*outcome:\s*\w+\s*)?$"
)


def _sanitize_memory_for_context(memory_block: str) -> str:
    """Strip ``| result: <prose>`` payloads from memory entries before injection.

    The model would otherwise imitate prior prose-narrated tool-result patterns
    in its next response, fabricating tool outputs as plain text without ever
    invoking a real tool. See the call-site comment in build_system_context.

    Plain log lines (no `task: ... | result: ...` shape) are passed through.
    """
    out: list[str] = []
    for line in memory_block.splitlines():
        m = _MEM_ENTRY_RE.match(line)
        if not m:
            out.append(line)
            continue
        task_part = m.group(1).rstrip()
        outcome_part = (m.group(2) or "").strip()
        if outcome_part:
            out.append(f"{task_part}  →  {outcome_part}")
        else:
            out.append(f"{task_part}  →  [completed; result omitted]")
    return "\n".join(out)


async def build_system_context(agent_dir: Path, config_text: str | None = None) -> str:
    """Assemble system prompt from agent's markdown files.

    Sections:
    - PROMPT.MD (always, in full)
    - MEMORY.MD (last ``context_memory_limit`` non-empty lines; default 10)
    - NOTES.MD (first ``context_notes_limit`` chars; default 3000)
    - HEALTH.MD (last ``context_health_limit`` non-empty lines; default 5)

    The defaults used here are the **token-bloat-safe** values. Any
    agent that actually needs more can bump them via its ``runner:`` block
    in ``CONFIG.yaml`` — that override still wins. But leaving them low by
    default caps the per-turn system prompt size for every agent at
    creation time, instead of relying on each agent to remember to set
    tight limits.
    """
    # Read CONFIG.yaml for limits (use pre-read text if provided)
    if config_text is None:
        config_text = await _read_if_exists(agent_dir / "CONFIG.yaml")
    runner = _parse_runner_config(config_text)
    memory_limit = runner.get("context_memory_limit", _settings.context_memory_lines)
    health_limit = runner.get("context_health_limit", _settings.context_health_lines)
    notes_chars = runner.get("context_notes_chars", _settings.context_notes_chars)
    learnings_chars = runner.get("context_learnings_chars", _settings.context_learnings_chars)
    knowledge_chars = runner.get("context_knowledge_chars", _settings.context_knowledge_chars)

    # Read all files
    prompt = await _read_if_exists(agent_dir / "PROMPT.MD")
    memory = await _read_if_exists(agent_dir / "MEMORY.MD")
    notes = await _read_if_exists(agent_dir / "NOTES.MD")
    health = await _read_if_exists(agent_dir / "HEALTH.MD")
    learnings = await _read_if_exists(agent_dir / "LEARNINGS.MD")
    knowledge = await _read_if_exists(_settings.agents_dir / "shared" / "KNOWLEDGE.MD")

    sections: list[str] = []

    # PROMPT.MD — always included
    if prompt.strip():
        sections.append(prompt.strip())

    # MEMORY.MD — last N lines, SANITIZED.
    #
    # MEMORY.MD entries embed the model's prior response text under
    # `| result: ...`. When the whole line is replayed as context, the model
    # imitates that prose pattern — narrating intent ("Let me check ...") and
    # then writing fabricated tool outputs as plain text, WITHOUT actually
    # invoking any tool. Observed live on master/deepseek-chat: 3/3 spawn
    # requests produced 1-turn, 0-tool-call responses with hallucinated PIDs
    # and result strings.
    #
    # Sanitize by stripping the `result:` payload before injection — keep the
    # task descriptor + outcome marker, drop the narrative the model would
    # otherwise imitate.
    if memory.strip():
        tail = _tail_lines(memory, memory_limit)
        if tail:
            tail = _sanitize_memory_for_context(tail)
            sections.append(f"## Recent Memory\n{tail}")

    # NOTES.MD — capped to prevent unbounded context growth
    if notes.strip():
        trimmed = notes.strip()[:notes_chars]
        sections.append(f"## Notes\n{trimmed}")

    # LEARNINGS.MD — capped
    if learnings.strip():
        trimmed = learnings.strip()[:learnings_chars]
        sections.append(f"## Learned Rules\n{trimmed}")

    # KNOWLEDGE.MD — shared, capped
    if knowledge.strip():
        trimmed = knowledge.strip()[:knowledge_chars]
        sections.append(f"## Shared Knowledge\n{trimmed}")

    # RAG hint — encourage using search_memory for past work
    try:
        from app.utils.db import get_db
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE agent = ?",
            (agent_dir.name,),
        ).fetchone()
        if row and row[0] > 0:
            sections.append(
                f"## Memory Index\n"
                f"{row[0]} past memories indexed. Use search_memory(query=...) "
                f"to find relevant past tasks, notes, and learnings."
            )
    except Exception:
        pass  # DB may not be initialized yet

    # HEALTH.MD — last N lines
    if health.strip():
        tail = _tail_lines(health, health_limit)
        if tail:
            sections.append(f"## Recent Health Log\n{tail}")

    # GOALS.MD — only for master agent
    goals_context = await build_goals_context(agent_dir)
    if goals_context:
        sections.append(goals_context)

    return "\n\n---\n\n".join(sections)


async def build_goals_context(agent_dir: Path) -> str:
    """Read GOALS.MD and format active goals for injection into master's context.

    Only returns content for agents that have a GOALS.MD file (typically master).
    Capped at 2000 chars.
    """
    goals_path = agent_dir / "GOALS.MD"
    if not goals_path.exists():
        return ""

    text = await _read_if_exists(goals_path)
    if not text.strip() or text.strip() == "# GOALS\n\n## Active\n\n## Backlog\n\n## Done":
        return ""

    # Extract active goals section
    active_match = re.search(
        r"## Active\s*\n(.*?)(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    if not active_match:
        return ""

    active_text = active_match.group(1).strip()
    if not active_text:
        return ""

    # Cap at 2000 chars -> removed: full goals content
    return f"## Active Goals\n{active_text}"
