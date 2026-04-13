"""Context assembly — build a full system prompt from agent files.

Reads PROMPT.MD, MEMORY.MD, NOTES.MD, and HEALTH.MD to give the agent
continuity across tasks without explicit notes_read calls.
"""

import re
from pathlib import Path

import aiofiles

from app.config import settings as _settings


def _parse_runner_config(config_text: str) -> dict[str, int | bool]:
    """Extract runner.* integer values and lifecycle.* booleans from CONFIG.md."""
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


def _tail_lines(text: str, n: int) -> str:
    """Return the last N non-empty lines from text."""
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-n:])


async def build_system_context(agent_dir: Path, config_text: str | None = None) -> str:
    """Assemble system prompt from agent's markdown files.

    Sections:
    - PROMPT.MD (always, in full)
    - MEMORY.MD (last ``context_memory_limit`` non-empty lines; default 10)
    - NOTES.MD (first ``context_notes_limit`` chars; default 3000)
    - HEALTH.MD (last ``context_health_limit`` non-empty lines; default 5)

    The defaults used here are the **token-bloat-safe** values. Any
    agent that actually needs more can bump them via its ``runner:`` block
    in ``CONFIG.md`` — that override still wins. But leaving them low by
    default caps the per-turn system prompt size for every agent at
    creation time, instead of relying on each agent to remember to set
    tight limits.
    """
    # Read CONFIG.md for limits (use pre-read text if provided)
    if config_text is None:
        config_text = await _read_if_exists(agent_dir / "CONFIG.md")
    runner = _parse_runner_config(config_text)
    memory_limit = runner.get("context_memory_limit", 10)
    health_limit = runner.get("context_health_limit", 5)
    notes_limit = runner.get("context_notes_limit", 3000)  # chars

    learnings_limit = runner.get("context_learnings_limit", 2000)  # chars
    knowledge_limit = runner.get("context_knowledge_limit", 1500)  # chars

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

    # MEMORY.MD — last N lines
    if memory.strip():
        tail = _tail_lines(memory, memory_limit)
        if tail:
            sections.append(f"## Recent Memory\n{tail}")

    # NOTES.MD — capped to notes_limit chars
    if notes.strip():
        trimmed = notes.strip()
        if len(trimmed) > notes_limit:
            trimmed = trimmed[:notes_limit] + "\n... (notes truncated — use notes_read for full content)"
        sections.append(f"## Notes\n{trimmed}")

    # LEARNINGS.MD — capped to learnings_limit chars
    if learnings.strip():
        trimmed = learnings.strip()
        if len(trimmed) > learnings_limit:
            trimmed = trimmed[:learnings_limit] + "\n... (learnings truncated)"
        sections.append(f"## Learned Rules\n{trimmed}")

    # KNOWLEDGE.MD — shared, newest entries, capped
    if knowledge.strip():
        trimmed = knowledge.strip()
        if len(trimmed) > knowledge_limit:
            trimmed = "... (older entries omitted)\n" + trimmed[-knowledge_limit:]
        sections.append(f"## Shared Knowledge\n{trimmed}")

    # HEALTH.MD — last N lines
    if health.strip():
        tail = _tail_lines(health, health_limit)
        if tail:
            sections.append(f"## Recent Health Log\n{tail}")

    return "\n\n---\n\n".join(sections)
