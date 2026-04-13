"""Agent management tools — create and delete dynamic agents."""

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.config import settings
from app.modules import CAPABILITY_MODULES

from . import BaseTool, RiskTier

_PROTECTED_NAMES = frozenset({
    "master", "planning", "builder", "keeper", "cron", "doctor", "base",
    "model_manager",
})

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]+$")

_AGENT_FILES = ("TASK.MD", "MEMORY.MD", "NOTES.MD", "HEALTH.MD")

_DEFAULT_TOOLS = [
    "file_read",
    "file_write",
    "file_edit",
    "file_delete",
    "file_list",
    "shell_exec",
    "memory_append",
    "notes_read",
    "notes_write",
    "health_log",
]


def _to_class_name(name: str) -> str:
    """Convert 'my-agent' or 'my_agent' to 'MyAgentAgent'."""
    parts = re.split(r"[-_]", name)
    return "".join(p.capitalize() for p in parts) + "Agent"


class CreateAgentTool(BaseTool):
    name = "create_agent"
    description = (
        "Create a new agent directory with PROMPT.MD, CONFIG.md, agent.py, and "
        "all standard agent files. Cannot overwrite existing agents or protected names."
    )
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Agent name (lowercase, alphanumeric + hyphens/underscores)",
            },
            "prompt": {
                "type": "string",
                "description": "System prompt content for PROMPT.MD",
            },
            "model": {
                "type": "string",
                "description": "LLM model to use (default: claude-sonnet-4-6)",
                "default": "claude-sonnet-4-6",
            },
            "adapter": {
                "type": "string",
                "description": "LLM adapter (default: anthropic)",
                "default": "anthropic",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to assign (default: basic file + memory tools)",
            },
            "modules": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Capability module names to compose the agent from. "
                    "Available: file_ops, web_research, config_management, "
                    "code_analysis, memory_management. Additive with 'tools'."
                ),
            },
            "temporary": {
                "type": "boolean",
                "description": "If true, agent self-terminates after task and is auto-deleted when result is read.",
                "default": False,
            },
        },
        "required": ["name", "prompt"],
    }

    def get_risk_tier(self, params: dict[str, Any]) -> RiskTier:
        if params.get("temporary", False):
            return RiskTier.AUTO
        return self.risk_tier

    async def execute(self, **params: Any) -> str:
        name = params["name"]
        prompt = params["prompt"]
        model = params.get("model", "claude-sonnet-4-6")
        adapter = params.get("adapter", "anthropic")
        tools = params.get("tools", _DEFAULT_TOOLS)
        modules = params.get("modules") or []
        temporary = params.get("temporary", False)

        # Validate name
        if not _NAME_PATTERN.match(name):
            return (
                f"ERROR: Invalid agent name '{name}'. "
                "Must start with lowercase letter, contain only [a-z0-9_-]."
            )
        if name in _PROTECTED_NAMES:
            return f"ERROR: '{name}' is a protected agent name and cannot be created."

        # Validate modules
        unknown = [m for m in modules if m not in CAPABILITY_MODULES]
        if unknown:
            return f"ERROR: Unknown capability module(s): {', '.join(unknown)}. Available: {', '.join(CAPABILITY_MODULES)}"

        agent_dir = settings.agents_dir / name
        if agent_dir.exists():
            return f"ERROR: Agent directory already exists: {agent_dir}"

        # Resolve modules — merge tools and prompt fragments
        prompt_fragments: list[str] = []
        sandbox_hints: dict[str, list[str]] = {}
        if modules:
            for mod_name in modules:
                mod = CAPABILITY_MODULES[mod_name]
                # Merge tools (union, no duplicates)
                for t in mod.tools:
                    if t not in tools:
                        tools.append(t) if isinstance(tools, list) else None
                prompt_fragments.append(mod.prompt_fragment)
                # Merge sandbox hints
                for key, vals in mod.sandbox_hints.items():
                    sandbox_hints.setdefault(key, []).extend(
                        v for v in vals if v not in sandbox_hints.get(key, [])
                    )

        # Create directory
        agent_dir.mkdir(parents=True)

        # Write PROMPT.MD (with module prompt fragments appended)
        full_prompt = prompt
        if prompt_fragments:
            full_prompt += "\n\n" + "\n\n".join(prompt_fragments)
        (agent_dir / "PROMPT.MD").write_text(full_prompt, encoding="utf-8")

        # Write CONFIG.md
        tools_block = "\n".join(f"  - {t}" for t in tools)
        config = (
            f"adapter: {adapter}\n"
            f"model: {model}\n"
            f"temperature: 0.3\n"
            f"tools:\n{tools_block}\n"
            f"runner:\n"
            f"  max_turns: 20\n"
            f"  task_timeout: 300\n"
            f"  poll_interval: 30\n"
            f"  retry_attempts: 3\n"
            f"  context_memory_limit: 50\n"
            f"  context_health_limit: 10\n"
        )
        if temporary:
            config += "lifecycle:\n  temporary: true\n"
        if sandbox_hints:
            config += "sandbox:\n"
            for hint_key, hint_vals in sandbox_hints.items():
                config += f"  {hint_key}:\n"
                for v in hint_vals:
                    config += f"    - {v}\n"
        (agent_dir / "CONFIG.md").write_text(config, encoding="utf-8")

        # Write empty standard files
        for fname in _AGENT_FILES:
            (agent_dir / fname).write_text("", encoding="utf-8")

        # Write agent.py
        class_name = _to_class_name(name)
        agent_py = (
            f"from app.agents.base import BaseAgent\n"
            f"from app.config import settings\n"
            f"\n"
            f"AGENTS_DIR = settings.agents_dir\n"
            f"\n"
            f"\n"
            f"class {class_name}(BaseAgent):\n"
            f"    def __init__(self) -> None:\n"
            f'        super().__init__(AGENTS_DIR / "{name}")\n'
            f"\n"
            f"\n"
            f'{name.replace("-", "_")}_agent = {class_name}()\n'
        )
        (agent_dir / "agent.py").write_text(agent_py, encoding="utf-8")

        # Write __init__.py
        var_name = f'{name.replace("-", "_")}_agent'
        init_py = (
            f"from .agent import {var_name}\n"
            f"\n"
            f'__all__ = ["{var_name}"]\n'
        )
        (agent_dir / "__init__.py").write_text(init_py, encoding="utf-8")

        suffix = " [temporary]" if temporary else ""
        mod_note = f" (modules: {', '.join(modules)})" if modules else ""
        return f"Created agent '{name}' at {agent_dir} with {len(tools)} tools{suffix}{mod_note}"


class DeleteAgentTool(BaseTool):
    name = "delete_agent"
    description = (
        "Delete a dynamic agent directory. Refuses protected agents and running agents."
    )
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the agent to delete",
            },
        },
        "required": ["name"],
    }

    async def execute(self, **params: Any) -> str:
        name = params["name"]

        if name in _PROTECTED_NAMES:
            return f"ERROR: '{name}' is a protected agent and cannot be deleted."

        agent_dir = settings.agents_dir / name
        if not agent_dir.exists():
            return f"ERROR: Agent '{name}' not found at {agent_dir}"

        # Check if running via STATUS.json
        status_path = agent_dir / "STATUS.json"
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text())
                if status.get("state") in ("running", "idle"):
                    pid = status.get("pid")
                    return (
                        f"ERROR: Agent '{name}' is currently {status['state']} "
                        f"(PID {pid}). Use kill_agent first."
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        # Promote learnings before deletion
        promoted = 0
        learnings_path = agent_dir / "LEARNINGS.MD"
        if learnings_path.exists():
            learnings_text = learnings_path.read_text(encoding="utf-8").strip()
            if learnings_text:
                knowledge_path = settings.agents_dir / "shared" / "KNOWLEDGE.MD"
                knowledge_path.parent.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                entry = (
                    f"\n[{now}] category: discovery | source: {name} (promoted)\n"
                    f"{learnings_text}\n"
                )
                try:
                    with open(knowledge_path, "a", encoding="utf-8") as f:
                        f.write(entry)
                    promoted = len([
                        l for l in learnings_text.splitlines()
                        if l.strip().startswith("### ")
                    ]) or 1
                except OSError:
                    pass

        shutil.rmtree(agent_dir)
        promo_note = f" ({promoted} learning(s) promoted to shared knowledge)" if promoted else ""
        return f"Deleted agent '{name}'{promo_note}"
