from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from app.utils.adapters import ToolDefinition


def truncate_tool_output(text: str, *, cap: int = 0, note: str = "") -> str:
    """No-op pass-through. All truncation caps have been removed."""
    return text


# ── Sandbox ───────────────────────────────────────────────────────────────

@dataclass
class SandboxPolicy:
    """Per-agent file/shell restrictions parsed from ``CONFIG.yaml``.

    Two independent policies live in one object:

    - ``forbidden_paths``: list of path prefixes (relative to project
      root) the agent must not write to, edit, or delete. Enforced by
      the file-mutating tools.
    - ``shell_allowlist``: list of command-name prefixes the agent is
      allowed to pass to ``shell_exec``. Empty list means "no
      restriction" (the existing behavior for agents that haven't
      opted in).

    Both lists are matched as simple string prefixes, not regex, to
    keep the policy auditable.
    """

    forbidden_paths: list[str] = field(default_factory=list)
    shell_allowlist: list[str] = field(default_factory=list)

    def is_forbidden(self, rel_path: str) -> bool:
        """True if ``rel_path`` (project-root-relative) sits under any
        forbidden prefix."""
        if not self.forbidden_paths:
            return False
        # Normalize the incoming path — no leading slash, forward slashes.
        p = rel_path.replace("\\", "/").lstrip("/")
        for prefix in self.forbidden_paths:
            fp = prefix.replace("\\", "/").lstrip("/").rstrip("/")
            if not fp:
                continue
            if p == fp or p.startswith(fp + "/") or p == fp + "/":
                return True
        return False

    def is_shell_allowed(self, command: str) -> bool:
        """True if the command is allowed under the shell allowlist.

        Empty allowlist means "no restriction". Otherwise the first
        whitespace-separated token of ``command`` must start with one
        of the allowed prefixes (so ``poetry add foo`` is allowed by
        allowlist ``["poetry"]``).
        """
        if not self.shell_allowlist:
            return True
        first = command.strip().split(None, 1)[0] if command.strip() else ""
        return any(first == prefix or first.startswith(prefix) for prefix in self.shell_allowlist)


def _parse_sandbox_policy(agent_dir: Path) -> SandboxPolicy:
    """Read ``CONFIG.yaml`` in ``agent_dir`` and extract the sandbox block.

    Expected YAML shape (we scan with simple regex — the project does not
    depend on PyYAML)::

        sandbox:
          forbidden:
            - app/agents/master/
            - .env
          shell_allowlist:
            - poetry
    """
    cfg = agent_dir / "CONFIG.yaml"
    if not cfg.exists():
        return SandboxPolicy()
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return SandboxPolicy()

    forbidden: list[str] = []
    shell_allowlist: list[str] = []
    in_sandbox = False
    current_list: list[str] | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped == "sandbox:" or stripped.startswith("sandbox:"):
            in_sandbox = True
            current_list = None
            continue
        if not in_sandbox:
            continue
        # Top-level key → exit sandbox block
        if stripped and not raw_line.startswith(" ") and not stripped.startswith("#"):
            break
        # Sub-block header (forbidden: / shell_allowlist: / personal_read_write:)
        m_key = re.match(r"^\s{2}(\w+):\s*$", raw_line)
        if m_key:
            key = m_key.group(1)
            if key == "forbidden":
                current_list = forbidden
            elif key == "shell_allowlist":
                current_list = shell_allowlist
            else:
                # Unknown sub-block — ignore values until next key
                current_list = None
            continue
        # List entry
        m_item = re.match(r"^\s+-\s+(.+?)\s*$", raw_line)
        if m_item and current_list is not None:
            current_list.append(m_item.group(1).strip())

    return SandboxPolicy(forbidden_paths=forbidden, shell_allowlist=shell_allowlist)


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    @abstractmethod
    async def execute(self, **params: Any) -> str: ...


# ── Registry ──────────────────────────────────────────────────────────────────

from .file import FileDeleteTool, FileEditTool, FileListTool, FileReadTool, FileWriteTool, ImageReadTool, ParseCsvTool
from .memory import AgentAmnesiaTool, HealthLogTool, LearningsAppendTool, MemoryAppendTool, NotesAppendTool, NotesReadTool, NotesWriteTool, SharedKnowledgeAppendTool
from .server import ProcessRestartTool, ServerRestartTool
from .shell import ShellExecTool
from .web import FetchPageTool, WebSearchTool
from .logs import ReadAgentLogsTool
from .delegation import (
    CheckTaskStatusTool,
    KillAgentTool,
    NotifyParentTool,
    PingAgentTool,
    ReadTaskResultTool,
    SpawnAgentTool,
    WaitForAgentTool,
    WaitForAgentsTool,
)
from .agent_mgmt import CreateAgentTool, DeleteAgentTool
from .agent_settings_tool import HealAgentSettingsTool, ShowAgentSettingsTool
from .config_update import UpdateConfigTool
from .model_manager import CheckModelAvailabilityTool, ListModelsTool, UpdateAgentConfigTool
from .search import SearchMemoryTool

TOOL_REGISTRY: dict[str, type[BaseTool]] = {
    "server_restart": ServerRestartTool,
    "process_restart": ProcessRestartTool,
    "shell_exec": ShellExecTool,
    "file_read": FileReadTool,
    "file_write": FileWriteTool,
    "file_edit": FileEditTool,
    "file_delete": FileDeleteTool,
    "file_list": FileListTool,
    "memory_append": MemoryAppendTool,
    "notes_read": NotesReadTool,
    "notes_write": NotesWriteTool,
    "notes_append": NotesAppendTool,
    "health_log": HealthLogTool,
    "learnings_append": LearningsAppendTool,
    "agent_amnesia": AgentAmnesiaTool,
    "web_search": WebSearchTool,
    "fetch_page": FetchPageTool,
    "spawn_agent": SpawnAgentTool,
    "ping_agent": PingAgentTool,
    "kill_agent": KillAgentTool,
    "check_task_status": CheckTaskStatusTool,
    "read_task_result": ReadTaskResultTool,
    "wait_for_agent": WaitForAgentTool,
    "wait_for_agents": WaitForAgentsTool,
    "notify_parent": NotifyParentTool,
    "read_agent_logs": ReadAgentLogsTool,
    "create_agent": CreateAgentTool,
    "delete_agent": DeleteAgentTool,
    "update_config": UpdateConfigTool,
    "check_model_availability": CheckModelAvailabilityTool,
    "list_models": ListModelsTool,
    "update_agent_config": UpdateAgentConfigTool,
    "heal_agent_settings": HealAgentSettingsTool,
    "show_agent_settings": ShowAgentSettingsTool,
    "search_memory": SearchMemoryTool,
    "shared_knowledge_append": SharedKnowledgeAppendTool,
    "image_read": ImageReadTool,
    "parse_csv": ParseCsvTool,
}

# Tools that need agent_dir injected
_AGENT_DIR_TOOLS = {
    "memory_append",
    "notes_read",
    "notes_write",
    "notes_append",
    "health_log",
    "learnings_append",
    "update_config",
    "spawn_agent",
    "notify_parent",
    "shared_knowledge_append",
    "server_restart",
}

# Tools that receive a SandboxPolicy kwarg. Only file-mutating and shell
# tools care; reads and delegation are unaffected.
_SANDBOX_TOOLS = {"file_write", "file_edit", "file_delete", "shell_exec"}


def build_tools(
    names: list[str],
    agent_dir: Path,
    *,
    session_id: str | None = None,
) -> list[BaseTool]:
    """Instantiate the requested tools for ``agent_dir``.

    Parses the caller's ``CONFIG.yaml`` sandbox block once and passes a
    :class:`SandboxPolicy` into every tool that cares. Agents without a
    sandbox block get an empty policy (no restrictions), preserving the
    pre-sandbox behavior.
    """
    policy = _parse_sandbox_policy(agent_dir)
    tools: list[BaseTool] = []
    for name in names:
        cls = TOOL_REGISTRY.get(name)
        if cls is None:
            continue
        kwargs: dict[str, Any] = {}
        if name in _AGENT_DIR_TOOLS:
            kwargs["agent_dir"] = agent_dir
            if name == "spawn_agent":
                kwargs["session_id"] = session_id
        if name in _SANDBOX_TOOLS:
            kwargs["sandbox"] = policy
        try:
            tools.append(cls(**kwargs))
        except TypeError:
            # Tool hasn't been updated to accept the new kwargs yet —
            # fall back to a bare constructor so we never hard-break.
            tools.append(cls())
    return tools
