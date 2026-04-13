"""OpenRouter adapter — unified access to 100+ models with full tool use.

OpenRouter is OpenAI-compatible (POST https://openrouter.ai/api/v1/chat/completions),
uses Bearer auth, and supports full tool use via the OpenAI `tools` parameter.
Models are namespaced: "anthropic/claude-sonnet-4-6", "openai/gpt-4o", etc.
"""

import json
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
from .normalize import normalize_to_openai

_OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_DEFAULT_CONTEXT_WINDOW = 128_000

# Module-level cache for dynamic model list
_cached_models: list[dict[str, Any]] | None = None


async def fetch_openrouter_models(api_key: str = "") -> list[dict[str, Any]]:
    """Fetch available models from OpenRouter API. Cached after first call."""
    global _cached_models
    if _cached_models is not None:
        return _cached_models

    key = api_key or settings.openrouter_api_key
    headers: dict[str, str] = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(_OPENROUTER_MODELS_URL, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            _cached_models = data.get("data", [])
            return _cached_models
    except (httpx.HTTPError, json.JSONDecodeError):
        return []


def _get_context_window_from_cache(model_id: str) -> int:
    """Look up context window from cached models list, fall back to static catalog."""
    if model_id in ALL_CONTEXT_WINDOWS:
        return ALL_CONTEXT_WINDOWS[model_id]
    if _cached_models:
        for m in _cached_models:
            if m.get("id") == model_id:
                return m.get("context_length", _DEFAULT_CONTEXT_WINDOW)
    return _DEFAULT_CONTEXT_WINDOW


class OpenRouterAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._api_key = settings.openrouter_api_key

    def context_window_size(self) -> int:
        return _get_context_window_from_cache(self._config.model)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://github.com/yapoc",
            "X-Title": "YAPOC",
        }

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
    ) -> str:
        payload = {
            "model": self._config.model,
            "messages": self._build_messages(system_prompt, user_message, history),
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _OPENROUTER_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            )
            response.raise_for_status()
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
                _OPENROUTER_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=120,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if text := delta.get("content"):
                                yield text

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
        tc_accum: dict[int, dict[str, Any]] = {}
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _OPENROUTER_API_URL,
                json=payload,
                headers=self._headers(),
                timeout=300,
            ) as response:
                response.raise_for_status()
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

                    # Tool call deltas (OpenAI streaming format)
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
            except json.JSONDecodeError:
                arguments = {}

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
