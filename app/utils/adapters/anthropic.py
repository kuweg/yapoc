import copy
import time
from typing import Any, AsyncIterator

import anthropic

from app.config import settings

from .base import (
    AgentConfig,
    BaseLLMAdapter,
    Message,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolDefinition,
    ToolStart,
    TurnComplete,
    UsageStats,
)

from .models import ALL_CONTEXT_WINDOWS
from .normalize import sanitize_tool_id


def _sanitize_tool_ids_in_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite tool_use / tool_result IDs to match Anthropic's ``[a-zA-Z0-9_-]+``.

    Cross-adapter fallback can hand us history whose tool IDs include
    ``.``, ``:`` or other chars that Moonshot/DeepSeek allow but Anthropic
    rejects. We deep-copy the affected messages so the caller's state is
    untouched.
    """
    if not messages:
        return messages

    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        new_content = []
        mutated = False
        for block in content:
            if not isinstance(block, dict):
                new_content.append(block)
                continue
            btype = block.get("type")
            if btype == "tool_use":
                orig_id = str(block.get("id", ""))
                fixed = sanitize_tool_id(orig_id)
                if fixed != orig_id:
                    block = {**block, "id": fixed}
                    mutated = True
            elif btype == "tool_result":
                orig_id = str(block.get("tool_use_id", ""))
                fixed = sanitize_tool_id(orig_id)
                if fixed != orig_id:
                    block = {**block, "tool_use_id": fixed}
                    mutated = True
            new_content.append(block)
        if mutated:
            out.append({**msg, "content": new_content})
        else:
            out.append(msg)
    return out

_DEFAULT_CONTEXT_WINDOW = 200_000


# Model families that take `thinking: {"type": "adaptive"}`. On these,
# `budget_tokens` is rejected (400) or deprecated, and sampling parameters are
# rejected on everything newer than 4.6. Anything not listed here is treated as
# a pre-4.6 model and keeps the fixed-budget form.
_ADAPTIVE_THINKING_MARKERS: tuple[str, ...] = (
    "opus-4-6", "opus-4-7", "opus-4-8", "opus-5",
    "sonnet-4-6", "sonnet-5",
    "fable-5", "mythos-5",
)


def _supports_adaptive_thinking(model: str) -> bool:
    """True when ``model`` takes adaptive thinking rather than a token budget."""
    name = (model or "").lower()
    return any(marker in name for marker in _ADAPTIVE_THINKING_MARKERS)


def build_thinking_kwargs(
    *, model: str, thinking_enabled: bool, temperature: float, budget_tokens: int
) -> dict[str, Any]:
    """Build the request kwargs for thinking, per the target model's API shape.

    Three shapes, and mixing them is a hard 400:

    * adaptive (4.6+) — ``{"type": "adaptive"}`` and NO ``budget_tokens``.
      ``display`` is set explicitly because it defaults to "omitted" on newer
      models, which would make the adapter's ThinkingDelta events stream empty
      strings. Adaptive auto-enables interleaved thinking, so the old beta
      header is unnecessary. Sampling parameters are rejected on adaptive
      models newer than 4.6, and adaptive never needed the temperature=1.0 the
      fixed-budget mode required — so temperature is omitted entirely here.
    * fixed budget (pre-4.6) — ``{"type": "enabled", "budget_tokens": N}``,
      with the interleaved beta header and temperature 1.0.
    * off — the agent's configured temperature, no thinking block.

    The bug this replaces sent ``{"type": "adaptive", "budget_tokens": N}``,
    which the API rejects with
    ``thinking.adaptive.budget_tokens: Extra inputs are not permitted`` — so
    every Anthropic request with thinking enabled was failing outright.
    """
    if not thinking_enabled:
        return {"temperature": temperature}
    if _supports_adaptive_thinking(model):
        return {"thinking": {"type": "adaptive", "display": "summarized"}}
    return {
        "thinking": {"type": "enabled", "budget_tokens": budget_tokens},
        "extra_headers": {"anthropic-beta": "interleaved-thinking-2025-05-14"},
        "temperature": 1.0,
    }


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError(
                "Anthropic API key is not set. "
                "Set ANTHROPIC_API_KEY in your .env file or environment."
            )
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            max_retries=5,
        )

    def context_window_size(self) -> int:
        return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)

    @staticmethod
    def _cached_system(text: str) -> list[dict[str, Any]]:
        """Wrap system prompt as a content block with cache_control for prompt caching."""
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _cached_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mark the last tool with cache_control so the full tool list is cached."""
        if not tools:
            return tools
        # Copy so we don't mutate the originals
        tools = [dict(t) for t in tools]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    @staticmethod
    def _cached_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add a cache_control breakpoint on the last message's final block.

        Anthropic prompt caching caches everything up to the most recent
        ``cache_control`` marker. ``system`` and the last tool definition are
        already cached; this function adds a fourth marker on the tail of
        the conversation so the *message history itself* is cached on
        subsequent turns.

        Effect: the next request within the 5-minute cache window reads
        the old prefix at 0.1× input cost instead of 1.0×. For a 20-turn
        agent loop with large tool results, this is roughly a 10× cost
        reduction on cumulative input tokens.

        The function returns a **deep-copied** messages list so the
        caller's state (which is then appended to across turns) is never
        mutated. We only touch the LAST block of the LAST message.
        """
        if not messages:
            return messages

        # Deep copy so we can mutate the tail without affecting the caller.
        out = copy.deepcopy(messages)
        last = out[-1]
        content = last.get("content")

        if isinstance(content, str):
            # Convert string content to a single text block with cache_control.
            last["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content:
            # Find the last block and attach cache_control to it.
            # Blocks are dicts like {"type": "text"|"tool_use"|"tool_result", ...}.
            last_block = content[-1]
            if isinstance(last_block, dict):
                last_block["cache_control"] = {"type": "ephemeral"}
        # Any other shape we leave alone rather than risk breaking the request.
        return out

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
        *,
        response_format: str | None = None,
    ) -> str:
        from app.utils.adapters.base import _apply_json_nudge, _resolve_response_format

        messages = []
        for msg in (history or []):
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        # Anthropic has no native JSON-mode parameter — always nudge via prompt.
        effective = _resolve_response_format(response_format, self._config)
        sp = _apply_json_nudge(system_prompt) if effective == "json" else system_prompt

        response = await self._client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._cached_system(sp),
            messages=messages,
            temperature=self._config.temperature,
        )
        return response.content[0].text

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        messages = []
        for msg in (history or []):
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        async with self._client.messages.stream(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._cached_system(system_prompt),
            messages=messages,
            temperature=self._config.temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        anthropic_tools = self._cached_tools([
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ])

        # Cross-adapter fallback can supply tool_use / tool_result IDs that
        # include characters Anthropic rejects (``^[a-zA-Z0-9_-]+$``).
        # Sanitize before caching so the cache hash stays stable.
        messages = _sanitize_tool_ids_in_messages(messages)

        # Cache the conversation prefix so each subsequent turn reads the
        # old message history at 0.1× input cost. This is the dominant
        # cost lever for multi-turn agent loops.
        cached_messages = self._cached_messages(messages)

        # Guard: Claude Opus 4+ rejects requests where the messages array ends
        # with an assistant role ("assistant prefill"). This should not happen
        # in normal flow, but can occur due to edge cases in the tool loop or
        # compaction. Strip any trailing assistant messages so the API call
        # always ends with a user turn.
        while cached_messages and cached_messages[-1].get("role") == "assistant":
            cached_messages = cached_messages[:-1]

        # Safety: if stripping left us with an empty messages list, the
        # conversation is malformed — raise a clear error rather than sending
        # an empty messages array to the API.
        if not cached_messages:
            raise ValueError(
                "stream_with_tools: messages array is empty after stripping "
                "trailing assistant messages. Cannot make an API call."
            )

        t_start = time.perf_counter()
        output_tokens = 0

        thinking_enabled = settings.enable_thinking
        extra_kw: dict[str, Any] = build_thinking_kwargs(
            model=self._config.model,
            thinking_enabled=thinking_enabled,
            temperature=self._config.temperature,
            budget_tokens=settings.thinking_budget_tokens,
        )

        async with self._client.messages.stream(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._cached_system(system_prompt),
            messages=cached_messages,
            tools=anthropic_tools,
            **extra_kw,
        ) as stream:
            if thinking_enabled:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "thinking_delta":
                            yield ThinkingDelta(event.delta.thinking)
                        elif event.delta.type == "text_delta":
                            output_tokens += 1
                            yield TextDelta(event.delta.text)
            else:
                async for text in stream.text_stream:
                    output_tokens += 1  # approximate; replaced by final usage below
                    yield TextDelta(text)
            final = await stream.get_final_message()

        elapsed = time.perf_counter() - t_start

        # Build assistant_content and tool_calls from the final message
        assistant_content: list[dict[str, Any]] = []
        tool_calls: list[ToolCall] = []

        for block in final.content:
            if block.type == "thinking":
                # Must be echoed back in multi-turn when extended thinking is enabled;
                # the API rejects the next request if thinking blocks are absent.
                assistant_content.append(
                    {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
                )
            elif block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
                tc = ToolCall(id=block.id, name=block.name, input=block.input)
                tool_calls.append(tc)
                yield ToolStart(name=block.name, input=block.input)

        # Emit usage stats using real token counts from the API
        usage = final.usage
        real_output = usage.output_tokens
        tps = real_output / elapsed if elapsed > 0 else 0.0

        yield UsageStats(
            input_tokens=usage.input_tokens,
            output_tokens=real_output,
            tokens_per_second=tps,
            context_window=self.context_window_size(),
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

        yield TurnComplete(
            stop_reason=final.stop_reason,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
        )
