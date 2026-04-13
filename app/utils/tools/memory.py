from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from . import BaseTool, RiskTier
from app.config import settings
from app.utils.secrets import scrub


class MemoryAppendTool(BaseTool):
    name = "memory_append"
    description = "Append a timestamped entry to your MEMORY.MD log."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "Text to append to memory log"},
        },
        "required": ["entry"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "MEMORY.MD"

    async def execute(self, **params: Any) -> str:
        entry = scrub(params["entry"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{timestamp}] {entry}\n"
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(line)
        return f"Appended to MEMORY.MD: {entry}"


class NotesReadTool(BaseTool):
    name = "notes_read"
    description = "Read the contents of your NOTES.MD file."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "NOTES.MD"

    async def execute(self, **params: Any) -> str:
        if not self._path.exists():
            return "(NOTES.MD is empty or does not exist)"
        async with aiofiles.open(self._path, encoding="utf-8") as f:
            content = await f.read()
        return content or "(NOTES.MD is empty)"


class NotesWriteTool(BaseTool):
    name = "notes_write"
    description = "Replace the entire contents of your NOTES.MD file."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "New contents for NOTES.MD"},
        },
        "required": ["content"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "NOTES.MD"

    async def execute(self, **params: Any) -> str:
        content = scrub(params["content"])
        async with aiofiles.open(self._path, "w", encoding="utf-8") as f:
            await f.write(content)
        return f"NOTES.MD updated ({len(content)} chars)"


class NotesAppendTool(BaseTool):
    name = "notes_append"
    description = (
        "Append new content to NOTES.MD without overwriting existing content. "
        "Use this to add a new finding, decision, or fact. "
        "Prefer this over notes_write unless you need to restructure the whole document."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Content to append."},
            "section": {
                "type": "string",
                "description": "Optional section heading (without ##). Creates '## <section>' if provided.",
            },
        },
        "required": ["content"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._agent_dir = agent_dir

    async def execute(self, **params: Any) -> str:
        content: str = scrub(params["content"])
        section: str | None = params.get("section")
        path = self._agent_dir / "NOTES.MD"
        if section:
            block = f"\n## {section}\n{content}\n"
        else:
            block = f"\n{content}\n"
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(block)
        return f"Appended {len(content)} chars to NOTES.MD."


class HealthLogTool(BaseTool):
    name = "health_log"
    description = "Append a log entry to your HEALTH.MD file."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Message to log"},
            "error": {"type": "string", "description": "Error message to log (alias for message, kept for backward compat)"},
            "level": {
                "type": "string",
                "enum": ["info", "warning", "error"],
                "description": "Log severity level (default: error)",
            },
            "context": {"type": "string", "description": "Additional context (optional)"},
        },
        "required": [],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "HEALTH.MD"

    async def execute(self, **params: Any) -> str:
        message = scrub(params.get("message") or params.get("error") or "")
        if not message:
            return "Error: 'message' (or 'error') parameter is required"
        level = params.get("level", "error").upper()
        context = params.get("context", "")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{timestamp}] {level}: {message}"
        if context:
            line += f" | context: {context}"
        line += "\n"
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(line)
        return f"Logged {level} to HEALTH.MD: {message}"


class LearningsAppendTool(BaseTool):
    name = "learnings_append"
    description = (
        "Append a learned rule to your LEARNINGS.MD file. Use this when you observe "
        "a pattern (same error or correction 2+ times) that should guide future behavior. "
        "Rules must be human-readable, specific, and include context about when to apply."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "rule_name": {
                "type": "string",
                "description": "Short rule name (e.g. 'Always check .npmrc before npm install')",
            },
            "context": {
                "type": "string",
                "description": "When/why this rule was observed (e.g. 'npm install fails without .npmrc on this project')",
            },
            "action": {
                "type": "string",
                "description": "What to do when this situation arises",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "How confident you are in this rule (default: medium)",
                "default": "medium",
            },
        },
        "required": ["rule_name", "context", "action"],
    }
    risk_tier = RiskTier.AUTO

    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "LEARNINGS.MD"

    async def execute(self, **params: Any) -> str:
        rule_name = scrub(params["rule_name"])
        context = scrub(params["context"])
        action = scrub(params["action"])
        confidence = params.get("confidence", "medium")
        timestamp = datetime.now().strftime("%Y-%m-%d")

        # Cap at 20 rules — count existing ## Rule: headers
        if self._path.exists():
            existing = self._path.read_text(encoding="utf-8")
            rule_count = existing.count("## Rule:")
            if rule_count >= 20:
                return (
                    "LEARNINGS.MD already has 20 rules (max). "
                    "Review and prune old rules with notes_write before adding new ones."
                )
        block = (
            f"\n## Rule: {rule_name}\n"
            f"- **Observed:** {timestamp}\n"
            f"- **Context:** {context}\n"
            f"- **Action:** {action}\n"
            f"- **Confidence:** {confidence}\n"
            f"\n"
        )
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(block)
        return f"Learning stored: {rule_name} (confidence: {confidence})"


class SharedKnowledgeAppendTool(BaseTool):
    """Append an entry to the project-wide shared KNOWLEDGE.MD file."""

    name = "shared_knowledge_append"
    description = (
        "Append a knowledge entry to the shared KNOWLEDGE.MD file that all agents can read. "
        "Use this to share project-wide discoveries, conventions, or facts that other agents "
        "should know. Entries are append-only — you cannot edit or delete existing entries."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The knowledge entry to share (1-3 sentences, specific and actionable)",
            },
            "category": {
                "type": "string",
                "enum": ["convention", "discovery", "warning", "decision"],
                "description": "Category of knowledge (default: discovery)",
            },
        },
        "required": ["content"],
    }
    risk_tier = RiskTier.AUTO

    def __init__(self, agent_dir: Path) -> None:
        self._agent_name = agent_dir.name
        self._path = settings.agents_dir / "shared" / "KNOWLEDGE.MD"

    async def execute(self, **params: Any) -> str:
        content = scrub(params["content"])
        category = params.get("category", "discovery")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Cap at 50 entries
        if self._path.exists():
            existing = self._path.read_text(encoding="utf-8")
            entry_count = existing.count("## Entry:")
            if entry_count >= 50:
                return (
                    "KNOWLEDGE.MD already has 50 entries (max). "
                    "Oldest entries should be pruned before adding new ones."
                )

        # Ensure directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        block = (
            f"\n## Entry: {category}\n"
            f"- **Source:** {self._agent_name}\n"
            f"- **Time:** {timestamp}\n"
            f"- **Content:** {content}\n"
        )
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(block)
        return f"Shared knowledge stored by {self._agent_name}: {content[:80]}"


_AGENT_AMNESIA_TARGETS = {"planning", "builder"}
_AGENT_AMNESIA_FILES = ("MEMORY.MD", "NOTES.MD")


class AgentAmnesiaTool(BaseTool):
    name = "agent_amnesia"
    description = (
        "Clear the memory files (MEMORY.MD, NOTES.MD) of a sub-agent. "
        "Use when an agent has accumulated contaminating or incorrect memory. "
        f"Allowed targets: {sorted(_AGENT_AMNESIA_TARGETS)}."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent to clear. One of: planning, builder.",
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.CONFIRM

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        if agent_name not in _AGENT_AMNESIA_TARGETS:
            return (
                f"Error: '{agent_name}' is not an allowed amnesia target. "
                f"Allowed: {sorted(_AGENT_AMNESIA_TARGETS)}"
            )
        agent_dir = settings.agents_dir / agent_name
        if not agent_dir.is_dir():
            return f"Error: agent directory not found: {agent_dir}"
        cleared = []
        for fname in _AGENT_AMNESIA_FILES:
            path = agent_dir / fname
            if path.exists():
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write("")
                cleared.append(fname)
        if cleared:
            return f"Agent '{agent_name}': cleared {', '.join(cleared)}."
        return f"Agent '{agent_name}': no memory files found to clear."


class AddTaskTraceTool(BaseTool):
    """Post a timestamped note to the agent's current task ticket on the dashboard."""

    name = "add_task_trace"
    description = (
        "Add a timestamped trace note to your current task ticket on the dashboard. "
        "Use this to record progress, decisions, or sub-steps so users can follow execution. "
        "The note appears in the ticket's Activity timeline immediately."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "Short description of what you are doing or have decided (1–2 sentences)",
            },
        },
        "required": ["note"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._agent_name = agent_dir.name

    async def execute(self, **params: Any) -> str:
        import httpx

        note = params["note"]
        base = settings.base_url
        lookup_url = f"{base}/api/tickets/by-agent/{self._agent_name}"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(lookup_url)
                if r.status_code != 200:
                    return f"Ticket lookup failed ({r.status_code}) — trace not recorded."
                ticket = r.json()
                if not ticket:
                    return f"No active ticket found for '{self._agent_name}' — trace not recorded."
                ticket_id = ticket["id"]
                r2 = await client.post(
                    f"{base}/api/tickets/{ticket_id}/trace",
                    json={"note": note, "agent": self._agent_name},
                )
            if r2.status_code == 200:
                return f"Trace recorded on ticket '{ticket_id}': {note}"
            return f"Failed to record trace: HTTP {r2.status_code}"
        except Exception as exc:
            return f"Trace error (non-fatal): {exc}"
