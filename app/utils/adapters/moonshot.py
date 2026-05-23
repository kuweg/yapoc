"""MoonshotAI adapter — OpenAI-compatible API.

MoonshotAI exposes an OpenAI-compatible chat/completions endpoint,
so this adapter reuses the same logic as OpenAIAdapter with a
different base URL and API key.
"""

import json
import asyncio
import logging
import time
from typing import Any, AsyncIterator

from loguru import logger as _log

import httpx

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


def _normalize_to_moonshot(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Anthropic-style history to Moonshot's chat-completions shape.

    Kimi-K2 thinking models require ``reasoning_content`` to be echoed back
    on every assistant tool_use message — otherwise the API rejects with
    "thinking is enabled but reasoning_content is missing". We extract any
    ``thinking`` / ``reasoning`` blocks from assistant_content and place
    them on the assistant message; if a tool_use is present but no
    thinking block was captured (e.g. cross-adapter fallback), we inject
    a single-space placeholder so the API accepts the request.

    Tool IDs are sanitized to ``[a-zA-Z0-9_-]+`` for cross-adapter
    consistency.
    """
    result: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            result.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []

            for block in content:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": sanitize_tool_id(str(block.get("id", ""))),
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
                elif btype == "thinking":
                    t = block.get("thinking", "")
                    if t:
                        reasoning_parts.append(t)
                elif btype == "reasoning":
                    t = block.get("text", block.get("reasoning", ""))
                    if t:
                        reasoning_parts.append(t)

            out: dict[str, Any] = {"role": "assistant"}
            combined_text = "\n".join(t for t in text_parts if t)
            out["content"] = combined_text or None
            if tool_calls:
                out["tool_calls"] = tool_calls
            if reasoning_parts:
                out["reasoning_content"] = "\n".join(reasoning_parts)
            elif tool_calls:
                # Required-but-missing fallback so the API accepts the message.
                out["reasoning_content"] = " "
            result.append(out)

        elif role == "user":
            tool_results: list[dict[str, Any]] = []
            text_parts_user: list[str] = []

            for block in content:
                if not isinstance(block, dict):
                    text_parts_user.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "tool_result":
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": sanitize_tool_id(str(block.get("tool_use_id", ""))),
                        "content": block.get("content", ""),
                    })
                elif btype == "text":
                    text_parts_user.append(block.get("text", ""))
                else:
                    text_parts_user.append(str(block))

            combined = "\n".join(t for t in text_parts_user if t)
            if combined:
                result.append({"role": "user", "content": combined})
            result.extend(tool_results)

        else:
            result.append({
                "role": role,
                "content": str(content) if not isinstance(content, str) else content,
            })

    return result

log = logging.getLogger(__name__)

_MOONSHOT_API_URL = "https://api.moonshot.ai/v1/chat/completions"

_DEFAULT_CONTEXT_WINDOW = 256_000


def _raise_with_detail(response: httpx.Response) -> None:
    """Raise an HTTPStatusError that includes MoonshotAI's error message."""
    if response.is_success:
        return
    try:
        body = response.json()
        detail = body.get("error", {}).get("message", response.text)
    except Exception:
        detail = response.text
    raise httpx.HTTPStatusError(
        f"MoonshotAI API error ({response.status_code}): {detail}",
        request=response.request,
        response=response,
    )


class MoonshotAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._api_key = settings.moonshot_api_key
        if not self._api_key:
            raise ValueError(
                "MoonshotAI API key is not set. "
                "Set MOONSHOTAI_API_KEY in your .env file or environment."
            )

    def context_window_size(self) -> int:
        return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _build_messages(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None,
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]
        for msg in (history or []):
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
        *,
        response_format: str | None = None,
    ) -> str:
        from app.utils.adapters.base import (
            _apply_json_nudge,
            _resolve_response_format,
            _supports_native_json,
        )

        effective = _resolve_response_format(response_format, self._config)
        sp = system_prompt
        json_param: dict | None = None
        if effective == "json":
            if _supports_native_json(self._config.model):
                json_param = {"response_format": {"type": "json_object"}}
            else:
                sp = _apply_json_nudge(system_prompt)

        payload = {
            "model": self._config.model,
            "messages": self._build_messages(sp, user_message, history),
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            **(json_param or {}),
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _MOONSHOT_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            )
            _raise_with_detail(response)
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._config.model,
            "messages": self._build_messages(system_prompt, user_message, history),
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _MOONSHOT_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _raise_with_detail(response)
                aiter_lines = response.aiter_lines()
                while True:
                    try:
                        async with asyncio.timeout(60):
                            line = await aiter_lines.__anext__()
                    except StopAsyncIteration:
                        break
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        # Convert Anthropic-format messages to Moonshot format, preserving
        # ``reasoning_content`` so kimi-k2 thinking models accept the request.
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(_normalize_to_moonshot(messages))

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": openai_messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if openai_tools:
            payload["tools"] = openai_tools

        t_start = time.perf_counter()

        # Accumulators for streaming tool calls
        # Map: tool_call index -> {id, name, arguments_parts}
        tc_accum: dict[int, dict[str, Any]] = {}
        reasoning_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _MOONSHOT_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=300,
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _raise_with_detail(response)
                aiter_lines = response.aiter_lines()
                while True:
                    try:
                        async with asyncio.timeout(60):
                            line = await aiter_lines.__anext__()
                    except StopAsyncIteration:
                        break
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])

                    # Usage in final chunk
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    # Reasoning content (kimi-k2 thinking models)
                    if reasoning := delta.get("reasoning_content"):
                        reasoning_parts.append(reasoning)
                        yield ThinkingDelta(reasoning)

                    # Text content
                    if text := delta.get("content"):
                        yield TextDelta(text)

                    # Tool call deltas
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta["index"]
                        if idx not in tc_accum:
                            tc_accum[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": tc_delta.get("function", {}).get("name", ""),
                                "arguments_parts": [],
                            }
                        else:
                            if tc_delta.get("id"):
                                tc_accum[idx]["id"] = tc_delta["id"]
                            if tc_delta.get("function", {}).get("name"):
                                tc_accum[idx]["name"] = tc_delta["function"]["name"]
                        if args_chunk := tc_delta.get("function", {}).get("arguments", ""):
                            tc_accum[idx]["arguments_parts"].append(args_chunk)

        elapsed = time.perf_counter() - t_start

        # Build tool calls and assistant_content
        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []

        # Preserve reasoning so subsequent turns can echo ``reasoning_content``
        # back to Moonshot (required when thinking is enabled) and so cross-
        # adapter fallback (e.g. deepseek) sees the same thinking block.
        if reasoning_parts:
            assistant_content.append(
                {"type": "thinking", "thinking": "".join(reasoning_parts)}
            )

        for idx in sorted(tc_accum):
            acc = tc_accum[idx]
            arguments_str = "".join(acc["arguments_parts"])
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError as exc:
                _log.bind(
                    tool=acc.get("name"), adapter="moonshot",
                    parts=len(acc["arguments_parts"]),
                ).warning(
                    "Tool-call args failed to parse ({}): {!r}",
                    exc, arguments_str[:400],
                )
                arguments = {
                    "__adapter_parse_error__": str(exc)[:120],
                    "__raw_args__": arguments_str[:400],
                }

            # Sanitize tool IDs so cross-adapter fallback (e.g. Anthropic,
            # which requires ``^[a-zA-Z0-9_-]+$``) accepts the replay.
            sanitized_id = sanitize_tool_id(acc["id"])
            tc = ToolCall(id=sanitized_id, name=acc["name"], input=arguments)
            tool_calls.append(tc)
            assistant_content.append({
                "type": "tool_use",
                "id": sanitized_id,
                "name": acc["name"],
                "input": arguments,
            })
            yield ToolStart(name=acc["name"], input=arguments)

        # Emit usage stats
        tps = output_tokens / elapsed if elapsed > 0 else 0.0
        yield UsageStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_per_second=tps,
            context_window=self.context_window_size(),
        )

        stop_reason = "tool_use" if tool_calls else "end_turn"
        yield TurnComplete(
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
        )
