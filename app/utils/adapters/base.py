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
    """Parse config from either [config] block (NOTES.MD) or bare YAML (CONFIG.md).

    Supports both formats:
      1. [config]\\nadapter: anthropic\\nmodel: ...  (NOTES.MD style)
      2. adapter: anthropic\\nmodel: ...             (CONFIG.md YAML style)
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
