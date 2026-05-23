"""OpenAI Codex adapter — uses the Responses API (/v1/responses).

Codex models (codex-mini-latest, etc.) require the Responses API, not
Chat Completions.  This adapter translates between the BaseAgent's
Anthropic-format messages and the Responses API wire format.

Responses API docs: https://platform.openai.com/docs/api-reference/responses
"""

import json
import asyncio
import logging
import time
from typing import Any, AsyncIterator

import httpx

from app.config import settings

from .base import (
    AgentConfig,
    BaseLLMAdapter,
    Message,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolDefinition,
    ToolStart,
    TurnComplete,
    UsageStats,
)
from .models import ALL_CONTEXT_WINDOWS

log = logging.getLogger(__name__)

_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
_DEFAULT_CONTEXT_WINDOW = 200_000


def _raise_with_detail(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
        detail = body.get("error", {}).get("message", response.text)
    except Exception:
        detail = response.text
    raise httpx.HTTPStatusError(
        f"Codex API error ({response.status_code}): {detail}",
        request=response.request,
        response=response,
    )


def _normalize_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to Responses API input items.

    Anthropic format:
      assistant with tool_use blocks → function_call items
      user with tool_result blocks → function_call_output items
      plain text messages → message items
    """
    items: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Plain string content
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            items.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            # Extract text and tool_use blocks
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    # Emit text accumulated so far
                    combined = "\n".join(t for t in text_parts if t)
                    if combined:
                        items.append({"role": "assistant", "content": combined})
                        text_parts = []
                    # Emit function_call item
                    items.append({
                        "type": "function_call",
                        "id": block["id"],
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    })

            # Remaining text
            combined = "\n".join(t for t in text_parts if t)
            if combined:
                items.append({"role": "assistant", "content": combined})

        elif role == "user":
            text_parts_user: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    text_parts_user.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "tool_result":
                    # Emit text first
                    combined = "\n".join(t for t in text_parts_user if t)
                    if combined:
                        items.append({"role": "user", "content": combined})
                        text_parts_user = []
                    # Emit function_call_output
                    items.append({
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": block.get("content", ""),
                    })
                elif btype == "text":
                    text_parts_user.append(block.get("text", ""))
                else:
                    text_parts_user.append(str(block))

            combined = "\n".join(t for t in text_parts_user if t)
            if combined:
                items.append({"role": "user", "content": combined})
        else:
            items.append({"role": role, "content": str(content) if not isinstance(content, str) else content})

    return items


class CodexAdapter(BaseLLMAdapter):
    """Adapter for OpenAI Codex models via the Responses API."""

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._api_key = settings.openai_api_key
        if not self._api_key:
            raise ValueError(
                "OpenAI API key is not set. "
                "Set OPENAI_API_KEY in your .env file or environment."
            )

    def context_window_size(self) -> int:
        return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
        *,
        response_format: str | None = None,
    ) -> str:
        from app.utils.adapters.base import _apply_json_nudge, _resolve_response_format

        # Codex (OpenAI Responses API) — all current models in the registry
        # have supports_json_mode=False. Use prompt nudge unconditionally;
        # revisit if a JSON-capable codex model lands in the registry.
        effective = _resolve_response_format(response_format, self._config)
        sp = _apply_json_nudge(system_prompt) if effective == "json" else system_prompt

        input_items: list[dict[str, Any]] = []
        for msg in (history or []):
            input_items.append({"role": msg.role, "content": msg.content})
        input_items.append({"role": "user", "content": user_message})

        payload: dict[str, Any] = {
            "model": self._config.model,
            "instructions": sp,
            "input": input_items,
            "max_output_tokens": self._config.max_tokens,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _RESPONSES_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            )
            _raise_with_detail(response)
            data = response.json()

        # Extract text from output
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        return part.get("text", "")
        return ""

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        input_items: list[dict[str, Any]] = []
        for msg in (history or []):
            input_items.append({"role": msg.role, "content": msg.content})
        input_items.append({"role": "user", "content": user_message})

        payload: dict[str, Any] = {
            "model": self._config.model,
            "instructions": system_prompt,
            "input": input_items,
            "max_output_tokens": self._config.max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _RESPONSES_API_URL,
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
                        async with asyncio.timeout(180):
                            line = await aiter_lines.__anext__()
                    except StopAsyncIteration:
                        break
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    chunk = json.loads(raw)
                    if chunk.get("type") == "response.output_text.delta":
                        delta = chunk.get("delta", "")
                        if delta:
                            yield delta

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        input_items = _normalize_to_responses_input(messages)

        api_tools = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in tools
        ]

        payload: dict[str, Any] = {
            "model": self._config.model,
            "instructions": system_prompt,
            "input": input_items,
            "max_output_tokens": self._config.max_tokens,
            "stream": True,
        }
        if api_tools:
            payload["tools"] = api_tools

        t_start = time.perf_counter()

        # Accumulators for function calls
        # Map: item_id → {call_id, name, arguments_parts}
        fc_accum: dict[str, dict[str, Any]] = {}
        text_emitted = False
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _RESPONSES_API_URL,
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
                        async with asyncio.timeout(180):
                            line = await aiter_lines.__anext__()
                    except StopAsyncIteration:
                        break
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    chunk = json.loads(raw)
                    event_type = chunk.get("type", "")

                    # Text delta
                    if event_type == "response.output_text.delta":
                        delta = chunk.get("delta", "")
                        if delta:
                            text_emitted = True
                            yield TextDelta(delta)

                    # Function call argument delta
                    elif event_type == "response.function_call_arguments.delta":
                        item_id = chunk.get("item_id", "")
                        if item_id not in fc_accum:
                            fc_accum[item_id] = {
                                "call_id": chunk.get("call_id", item_id),
                                "name": "",
                                "arguments_parts": [],
                            }
                        delta = chunk.get("delta", "")
                        if delta:
                            fc_accum[item_id]["arguments_parts"].append(delta)

                    # Function call complete — get the name
                    elif event_type == "response.output_item.done":
                        item = chunk.get("item", {})
                        if item.get("type") == "function_call":
                            item_id = item.get("id", "")
                            if item_id in fc_accum:
                                fc_accum[item_id]["name"] = item.get("name", "")
                                fc_accum[item_id]["call_id"] = item.get("call_id", item_id)
                            else:
                                fc_accum[item_id] = {
                                    "call_id": item.get("call_id", item_id),
                                    "name": item.get("name", ""),
                                    "arguments_parts": [item.get("arguments", "{}")],
                                }

                    # Response complete — get usage
                    elif event_type == "response.completed":
                        resp = chunk.get("response", {})
                        usage = resp.get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)

        elapsed = time.perf_counter() - t_start

        # Build tool calls
        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []

        for item_id, acc in fc_accum.items():
            arguments_str = "".join(acc["arguments_parts"])
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                arguments = {}

            call_id = acc["call_id"]
            tc = ToolCall(id=call_id, name=acc["name"], input=arguments)
            tool_calls.append(tc)
            assistant_content.append({
                "type": "tool_use",
                "id": call_id,
                "name": acc["name"],
                "input": arguments,
            })
            yield ToolStart(name=acc["name"], input=arguments)

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
