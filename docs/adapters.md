# LLM Adapters

Agents are not tied to a single LLM provider. Each agent can be configured to use a different adapter, allowing mixing of providers within the same system (e.g., Master Agent on Claude, Builder Agent on a local Ollama model).

---

## Interface

Every adapter must implement the following contract:

```python
class BaseLLMAdapter(ABC):

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> str:
        """Send a prompt and return the model's text response."""
        ...

    @abstractmethod
    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the response token by token."""
        ...

    @abstractmethod
    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """Stream a response with tool-use support (multi-turn)."""
        ...

    @property
    def model_id(self) -> str:
        """Human-readable identifier: e.g. 'claude-sonnet-4-6', 'gpt-4o', 'llama3'."""
        ...

    def context_window_size(self) -> int:
        """Return the context window size for the current model."""
        ...
```

`Message` is a simple dataclass: `role: str` (`"user"` | `"assistant"`) and `content: str`.

`AgentConfig` contains: `adapter`, `model`, `temperature`, `max_tokens`.

---

## Built-in Adapters

| Adapter | Provider | Tool Use | Notes |
|---|---|---|---|
| `AnthropicAdapter` | Anthropic Claude | Full | Default. Requires `ANTHROPIC_API_KEY`. Native tool-use support. |
| `OpenAIAdapter` | OpenAI | Full | Requires `OPENAI_API_KEY`. Streaming tool call accumulation. |
| `OllamaAdapter` | Ollama (local) | Full | No API key. Requires running Ollama server with tool-capable model. |
| `OpenRouterAdapter` | OpenRouter (100+ models) | Full | Requires `OPENROUTER_API_KEY`. OpenAI-compatible API with unified access. |

---

## File Location

```
app/utils/adapters/
    __init__.py       # Registry + re-exports
    base.py           # BaseLLMAdapter + AgentConfig + stream event types
    normalize.py      # Shared message format converters (Anthropic → OpenAI/Ollama)
    anthropic.py      # AnthropicAdapter
    openai.py         # OpenAIAdapter
    ollama.py         # OllamaAdapter
    openrouter.py     # OpenRouterAdapter
```

---

## Message Normalization

BaseAgent builds messages in Anthropic format (tool_use / tool_result content blocks). Non-Anthropic adapters use shared normalization functions from `normalize.py`:

| Anthropic (from BaseAgent) | OpenAI / OpenRouter | Ollama |
|---|---|---|
| `{role: "assistant", content: [{type: "tool_use", id, name, input}]}` | `{role: "assistant", tool_calls: [{id, type: "function", function: {name, arguments}}]}` | `{role: "assistant", tool_calls: [{function: {name, arguments}}]}` |
| `{role: "user", content: [{type: "tool_result", tool_use_id, content}]}` | `{role: "tool", tool_call_id, content}` (separate messages) | `{role: "tool", content}` (separate messages) |

Functions:
- `normalize_to_openai(messages)` — used by OpenAI and OpenRouter adapters
- `normalize_to_ollama(messages)` — used by Ollama adapter

---

## Agent Configuration

Each agent declares its adapter in its `CONFIG.md`:

```yaml
adapter: anthropic
model: claude-sonnet-4-6
temperature: 0.3
max_tokens: 8096
```

The agent runner reads `CONFIG.md` at startup and instantiates the correct adapter. If no config is present, the system falls back to the default defined in `.env`:

```env
DEFAULT_ADAPTER=anthropic
DEFAULT_MODEL=claude-sonnet-4-6
```

### Config Change Detection

`BaseAgent` tracks the last-loaded config (`_last_config`). When `CONFIG.md` changes between turns (e.g., via `update_config` tool or manual edit), the change is automatically detected and logged to `HEALTH.MD` with a `CONFIG_CHANGE:` prefix.

---

## Self-Optimization

Agents with the `update_config` tool can modify their own `CONFIG.md` to switch models. Safety controls:

| Layer | Mechanism |
|---|---|
| Kill switch | `ALLOW_SELF_OPTIMIZATION=false` (default) in `.env` |
| Approval gate | `RiskTier.CONFIRM` — human must approve every change |
| Audit trail | Logged to `HEALTH.MD` with `SELF_OPT:` prefix |
| Per-agent opt-in | Only agents with `update_config` in their tools list |
| Doctor monitoring | Doctor reads `SELF_OPT:` entries and writes `OPTIMIZATION_SUGGESTION:` warnings |

---

## OpenRouter

OpenRouter provides unified access to 100+ models via an OpenAI-compatible API.

### Setup

```env
OPENROUTER_API_KEY=sk-or-...
```

### Model Naming

Models use namespaced IDs: `provider/model-name`

```yaml
adapter: openrouter
model: anthropic/claude-sonnet-4-6
```

### Dynamic Model List

The CLI `yapoc models list` command fetches available models from `GET /api/v1/models` when OpenRouter is selected. A static fallback list is used when the API key is missing or the fetch fails.

### Pricing

OpenRouter pricing varies by model. The CLI's cost tracking includes pricing for popular OpenRouter models. Unknown models fall back to $0.00.

---

## Adding a New Adapter

1. Create `app/utils/adapters/<provider>.py`
2. Subclass `BaseLLMAdapter` and implement `complete`, `stream`, `stream_with_tools`, and `context_window_size`
3. If the API uses a different message format, add normalization to `normalize.py` or use the existing `normalize_to_openai()` if OpenAI-compatible
4. Register it in `app/utils/adapters/__init__.py`:

```python
ADAPTER_REGISTRY = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
    "ollama": OllamaAdapter,
    "openrouter": OpenRouterAdapter,
    "my_provider": MyProviderAdapter,  # add here
}
```

The agent runner resolves adapters by name from this registry — no other changes needed.
