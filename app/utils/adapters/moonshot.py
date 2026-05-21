"""MoonshotAI adapter — OpenAI-compatible API.

MoonshotAI exposes an OpenAI-compatible chat/completions endpoint,
so this adapter reuses the same logic as OpenAIAdapter with a
different base URL and API key.
"""

import json
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
    ToolCall,
    ToolDefinition,
    ToolStart,
    TurnComplete,
    UsageStats,
)
from .models import ALL_CONTEXT_WINDOWS
from .normalize import normalize_to_openai

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
                async for line in response.aiter_lines():
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
        # Convert Anthropic-format messages to OpenAI format
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(normalize_to_openai(messages))

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
                async for line in response.aiter_lines():
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

            tc = ToolCall(id=acc["id"], name=acc["name"], input=arguments)
            tool_calls.append(tc)
            assistant_content.append({
                "type": "tool_use",
                "id": acc["id"],
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
