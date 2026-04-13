# app/utils/adapters — LLM Adapter Registry

## Registry
```python
ADAPTER_REGISTRY = {"anthropic": AnthropicAdapter, "openai": OpenAIAdapter,
                    "ollama": OllamaAdapter, "openrouter": OpenRouterAdapter}

get_adapter(config: AgentConfig) -> BaseLLMAdapter
```

## Key types (base.py)

```python
@dataclass class AgentConfig:
    adapter: str; model: str; temperature: float; max_tokens: int

# Stream events emitted by stream_with_tools():
TextDelta(text)
ToolStart(name, input)
ToolDone(name, result, is_error)
TurnComplete(stop_reason, tool_calls, assistant_content)
UsageStats(input_tokens, output_tokens, tokens_per_second, context_window,
           cache_creation_tokens, cache_read_tokens)
CompactEvent(reason, tokens_before, tokens_after)

StreamEvent = TextDelta | ToolStart | ToolDone | TurnComplete | UsageStats | CompactEvent
```

## BaseLLMAdapter interface
```python
complete(system_prompt, user_message, history) -> str
stream(system_prompt, user_message, history) -> AsyncIterator[str]
stream_with_tools(system_prompt, messages, tools) -> AsyncIterator[StreamEvent]
context_window_size() -> int   # defaults to 200_000; overridden from models.ALL_CONTEXT_WINDOWS
```

## Adapter specifics

### AnthropicAdapter
- Uses `anthropic.AsyncAnthropic` SDK with `max_retries=5`
- **Always enables prompt caching**: system prompt gets `cache_control: ephemeral`; last tool definition gets cache control. First call in a new cache window pays full input price.

### OpenAIAdapter
- Raw `httpx` (no openai package)
- o-series models (`o1/o3/o4-*`): uses `max_completion_tokens` instead of `max_tokens`
- Uses `normalize.py` to convert messages to OpenAI format

### OpenRouterAdapter
- OpenAI-compatible endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Model names are namespaced: `anthropic/claude-sonnet-4-6`, `openai/gpt-4o`, etc.
- Module-level cache for dynamic model list

### OllamaAdapter
- Raw `httpx` to `settings.ollama_base_url` (`http://localhost:11434`)

## models/ subpackage
Contains: `MODEL_REGISTRY`, `PROVIDER_MODELS`, `ALL_PRICING`, `ALL_CONTEXT_WINDOWS`

Used by:
- `ModelManagerAgent.run_model_audit()` — validates agent configs
- `TurnRenderer.calc_cost()` — cost calculation
- `BaseLLMAdapter.context_window_size()` — context window lookup

## parse_config_block(content) -> dict
Dual-format YAML parser. Handles both:
- Bare YAML (CONFIG.md format)
- `[config]` block inside NOTES.MD (legacy)

Returns flat `dict[str, str]`.
