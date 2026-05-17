import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Message:
    role: str
    content: str


@dataclass
class AgentConfig:
    adapter: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 8096
    # Default output format for the agent. ``None`` or ``"text"`` is plain
    # text (current behavior). ``"json"`` requests a JSON object — adapters
    # pass the provider-native parameter when supported, otherwise fall
    # back to a system-prompt nudge. Per-call overrides take precedence
    # over this default. See `_resolve_response_format`.
    response_format: str | None = None


# ── JSON-mode helpers ────────────────────────────────────────────────────────


_JSON_NUDGE = (
    "\n\nIMPORTANT: Respond with a single valid JSON object. "
    "No prose before or after. No markdown code fences. "
    "Just raw JSON."
)


def _resolve_response_format(
    per_call: str | None, config: AgentConfig
) -> str | None:
    """Combine the per-call override and the agent-level default.

    Per-call wins. Returns lower-cased ``"json"`` / ``"text"`` / ``None``.
    """
    if per_call is not None:
        return per_call.lower() or None
    if config.response_format is None:
        return None
    return config.response_format.lower() or None


def _supports_native_json(model_id: str) -> bool:
    """Look up the model in the registry and return its JSON-mode flag.

    Returns False for unknown models — safer to nudge than to send a
    parameter the provider rejects.
    """
    try:
        from app.utils.adapters.models import MODEL_REGISTRY
    except ImportError:
        return False
    info = MODEL_REGISTRY.get(model_id)
    return bool(getattr(info, "supports_json_mode", False))


def _apply_json_nudge(system_prompt: str) -> str:
    """Append the JSON-only instruction to the system prompt.

    Used by adapters whose models lack native JSON mode (Anthropic, Codex,
    or any model whose ``supports_json_mode`` is False in the registry).
    """
    return (system_prompt or "") + _JSON_NUDGE


# ── Tool-use data model ──────────────────────────────────────────────────────


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


# ── Stream events ─────────────────────────────────────────────────────────────


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolStart:
    name: str
    input: dict[str, Any]


@dataclass
class ToolDone:
    name: str
    result: str
    is_error: bool = False


@dataclass
class TurnComplete:
    stop_reason: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    assistant_content: list[dict[str, Any]] = field(default_factory=list)



@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    tokens_per_second: float
    context_window: int  # model's total context window
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class CompactEvent:
    reason: str        # "auto" | "manual"
    tokens_before: int
    tokens_after: int


StreamEvent = TextDelta | ThinkingDelta | ToolStart | ToolDone | TurnComplete | UsageStats | CompactEvent


class BaseLLMAdapter(ABC):
    def __init__(self, config: AgentConfig) -> None:
        self._config = config

    @property
    def model_id(self) -> str:
        return self._config.model

    def context_window_size(self) -> int:
        """Return the context window size for the current model. Override in subclasses."""
        return 200_000

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
        *,
        response_format: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]: ...


def parse_config_block(content: str) -> dict:
    """Parse config from either [config] block (NOTES.MD) or bare YAML (CONFIG.yaml).

    Supports both formats:
      1. [config]\\nadapter: anthropic\\nmodel: ...  (NOTES.MD style)
      2. adapter: anthropic\\nmodel: ...             (CONFIG.yaml YAML style)
    """
    # Try [config] block first
    match = re.search(r"\[config\](.*?)(?:\n\[|\Z)", content, re.DOTALL | re.IGNORECASE)
    lines = match.group(1).strip().splitlines() if match else content.strip().splitlines()

    result = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result
