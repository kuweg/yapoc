"""Skill system tools — load_skills and create_skill.

Skills are YAML files stored in ``app/projects/skills/`` with progressive
disclosure at three levels:

- **Level 1**: One-line summary — injected into every agent's system prompt.
- **Level 2**: Parameters and expected inputs — loaded on demand by agents.
- **Level 3**: Full step-by-step procedure — loaded when an agent needs to
  execute the skill.
"""

import re
from pathlib import Path
from typing import Any

import aiofiles
import yaml

from . import BaseTool

SKILLS_DIR = Path("app/projects/skills")
_SKILL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _list_skill_files() -> list[Path]:
    """Return all ``*.yaml`` files under the skills directory, sorted by name."""
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(SKILLS_DIR.glob("*.yaml"))


async def _read_skill(name: str) -> dict[str, Any] | None:
    """Read a single skill YAML file by name (without ``.yaml``)."""
    path = SKILLS_DIR / f"{name}.yaml"
    if not path.exists():
        return None
    async with aiofiles.open(path, encoding="utf-8") as f:
        raw = await f.read()
    return yaml.safe_load(raw)


async def load_skills_summaries() -> str:
    """Load Level 1 summaries of ALL skills.

    Returns a formatted markdown block for injection into system prompts.
    """
    files = _list_skill_files()
    if not files:
        return "(No skills registered yet)"

    lines: list[str] = []
    for path in files:
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                raw = await f.read()
            data = yaml.safe_load(raw)
            if not isinstance(data, dict):
                continue
            name = data.get("name", path.stem)
            level_1 = data.get("level_1", data.get("summary", ""))
            lines.append(f"- {name}: {level_1}")
        except Exception:
            # Silently skip corrupt files
            continue

    if not lines:
        return "(No skills registered yet)"

    return "\n".join(lines)


# ── Tools ────────────────────────────────────────────────────────────────


class LoadSkillsTool(BaseTool):
    name = "load_skills"
    description = (
        "Load one or more skills at a specific disclosure level. "
        "Skills are stored as YAML files in app/projects/skills/ with "
        "three levels: Level 1 (summary), Level 2 (parameters), "
        "Level 3 (full procedure). Use this tool when you need the "
        "detailed instructions for a named skill."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of skill names to load (e.g., ['git_commit', 'docker_build'])",
            },
            "level": {
                "type": "integer",
                "description": "Disclosure level (1=summary, 2=parameters, 3=full procedure)",
                "minimum": 1,
                "maximum": 3,
            },
        },
        "required": ["names", "level"],
    }

    async def execute(self, **params: Any) -> str:
        names: list[str] = params.get("names", [])
        level: int = params.get("level", 1)

        if not names:
            return "Error: 'names' cannot be empty."

        level_key = f"level_{level}"
        results: list[str] = []

        for name in names:
            try:
                data = await _read_skill(name)
            except Exception as exc:
                results.append(f"- {name}: **Error reading skill file**: {exc}")
                continue

            if data is None:
                results.append(f"- {name}: **Skill not found** — no file at app/projects/skills/{name}.yaml")
                continue

            content = data.get(level_key)
            if not content:
                available = [f"level_{i}" for i in (1, 2, 3) if data.get(f"level_{i}")]
                results.append(
                    f"- {name}: **Level {level} not available**. "
                    f"Available levels: {', '.join(available) if available else 'none'}"
                )
                continue

            results.append(f"## {name} (Level {level})\n{content}")

        return "\n\n".join(results)


class CreateSkillTool(BaseTool):
    name = "create_skill"
    description = (
        "Create a new skill YAML file in app/projects/skills/. "
        "A skill has three disclosure levels: Level 1 (one-line summary), "
        "Level 2 (parameters and inputs), Level 3 (full step-by-step "
        "procedure). Once created, the skill is immediately available to "
        "all agents — no restart needed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name — alphanumeric and underscores only (e.g., deploy_check)",
                "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
            },
            "summary": {
                "type": "string",
                "description": "One-line summary of what this skill does (max 120 chars)",
            },
            "description": {
                "type": "string",
                "description": "Full description of the skill's purpose and use cases",
            },
            "level_1": {
                "type": "string",
                "description": "Level 1 content — short summary displayed in agent prompts",
            },
            "level_2": {
                "type": "string",
                "description": "Level 2 content — parameters, inputs, expected formats",
            },
            "level_3": {
                "type": "string",
                "description": "Level 3 content — full step-by-step procedure",
            },
        },
        "required": ["name", "summary", "level_1"],
    }

    async def execute(self, **params: Any) -> str:
        name: str = params.get("name", "").strip()

        if not _SKILL_NAME_RE.match(name):
            return (
                f"Error: Invalid skill name '{name}'. "
                f"Names must start with a letter or underscore and contain only "
                f"alphanumeric characters and underscores."
            )

        # Build the YAML document manually so we control formatting
        summary = params.get("summary", "").strip()
        description = params.get("description", "").strip()
        level_1 = params.get("level_1", "").strip()
        level_2 = params.get("level_2", "").strip()
        level_3 = params.get("level_3", "").strip()

        # Validate: summary is not too long for a prompt injection line
        if len(summary) > 120:
            return f"Error: Summary is {len(summary)} chars (max 120). Shorten it."

        lines = [f"name: {name}"]
        lines.append(f"summary: {summary}")
        if description:
            # Multi-line YAML with |
            lines.append("description: |")
            for desc_line in description.split("\n"):
                lines.append(f"  {desc_line}")
        if level_1:
            lines.append(f"level_1: \"{level_1}\"")
        if level_2:
            lines.append("level_2: |")
            for l2_line in level_2.split("\n"):
                lines.append(f"  {l2_line}")
        if level_3:
            lines.append("level_3: |")
            for l3_line in level_3.split("\n"):
                lines.append(f"  {l3_line}")

        yaml_content = "\n".join(lines)

        path = SKILLS_DIR / f"{name}.yaml"
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return f"Error: Skill '{name}' already exists at {path}. Delete it first or use a different name."

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(yaml_content + "\n")

        return f"Skill '{name}' created at {path}. It is now available to all agents."


__all__ = ["LoadSkillsTool", "CreateSkillTool"]
