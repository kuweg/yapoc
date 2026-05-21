from .anthropic import AnthropicAdapter
from .codex import CodexAdapter
from .deepseek import DeepSeekAdapter
from .moonshot import MoonshotAdapter
from .base import (
    AgentConfig,
    BaseLLMAdapter,
    CompactEvent,
    Message,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolDefinition,
    ToolDone,
    ToolResult,
    ToolStart,
    TurnComplete,
    UsageStats,
    parse_config_block,
)
from .fallback import FallbackAdapter
from .google import GoogleAdapter
from .lmstudio import LMStudioAdapter
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter
from .openrouter import OpenRouterAdapter

ADAPTER_REGISTRY: dict[str, type[BaseLLMAdapter]] = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
    "codex": CodexAdapter,
    "deepseek": DeepSeekAdapter,
    "ollama": OllamaAdapter,
    "openrouter": OpenRouterAdapter,
    "google": GoogleAdapter,
    "lmstudio": LMStudioAdapter,
    "moonshot": MoonshotAdapter,
}


def get_adapter(config: AgentConfig) -> BaseLLMAdapter:
    adapter_cls = ADAPTER_REGISTRY.get(config.adapter)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown adapter '{config.adapter}'. Available: {list(ADAPTER_REGISTRY)}"
        )
    return adapter_cls(config)


__all__ = [
    "Message",
    "AgentConfig",
    "BaseLLMAdapter",
    "CompactEvent",
    "parse_config_block",
    "ToolDefinition",
    "ToolCall",
    "ToolResult",
    "TextDelta",
    "ThinkingDelta",
    "ToolStart",
    "ToolDone",
    "TurnComplete",
    "UsageStats",
    "StreamEvent",
    "ADAPTER_REGISTRY",
    "get_adapter",
    "AnthropicAdapter",
    "OpenAIAdapter",
    "OllamaAdapter",
    "OpenRouterAdapter",
    "GoogleAdapter",
    "LMStudioAdapter",
    "CodexAdapter",
    "DeepSeekAdapter",
    "MoonshotAdapter",
    "FallbackAdapter",
]
