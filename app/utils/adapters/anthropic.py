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

_DEFAULT_CONTEXT_WINDOW = 200_000


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
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
    ) -> str:
        messages = []
        for msg in (history or []):
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        response = await self._client.messages.create(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._cached_system(system_prompt),
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
        temperature = 1.0 if thinking_enabled else self._config.temperature
        extra_kw: dict[str, Any] = {}
        if thinking_enabled:
            extra_kw["thinking"] = {"type": "enabled", "budget_tokens": settings.thinking_budget_tokens}
            extra_kw["extra_headers"] = {"anthropic-beta": "interleaved-thinking-2025-05-14"}

        async with self._client.messages.stream(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=self._cached_system(system_prompt),
            messages=cached_messages,
            temperature=temperature,
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
