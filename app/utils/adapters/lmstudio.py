"""LM Studio adapter — local models via OpenAI-compatible server.

LM Studio exposes a local OpenAI-compatible HTTP server (default
http://localhost:1234/v1). Models are whatever the user has loaded.
No API key is required by default.

See docs/llmstudio-guide.md for setup instructions.
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

_DEFAULT_CONTEXT_WINDOW = 32_768


def _raise_with_detail(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
        detail = body.get("error", {}).get("message", response.text)
    except Exception:
        detail = response.text
    raise httpx.HTTPStatusError(
        f"LM Studio API error ({response.status_code}): {detail}",
        request=response.request,
        response=response,
    )


class LMStudioAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._base_url = settings.lmstudio_base_url.rstrip("/")
        # LM Studio typically has no key, but supports one if user configured
        self._api_key = settings.lmstudio_api_key or "lm-studio"

    @property
    def _chat_url(self) -> str:
        return f"{self._base_url}/v1/chat/completions"

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
    ) -> str:
        payload = {
            "model": self._config.model,
            "messages": self._build_messages(system_prompt, user_message, history),
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._chat_url,
                json=payload,
                headers=self._headers(),
                timeout=300,
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
                self._chat_url,
                json=payload,
                headers=self._headers(),
                timeout=300,
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _raise_with_detail(response)
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
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

        tc_accum: dict[int, dict[str, Any]] = {}
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._chat_url,
                json=payload,
                headers=self._headers(),
                timeout=600,
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _raise_with_detail(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])

                    if chunk.get("usage"):
                        usage = chunk["usage"]
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    if text := delta.get("content"):
                        yield TextDelta(text)

                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
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

        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []

        for idx in sorted(tc_accum):
            acc = tc_accum[idx]
            arguments_str = "".join(acc["arguments_parts"])
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                arguments = {}

            tc = ToolCall(id=acc["id"] or f"tc_{idx}", name=acc["name"], input=arguments)
            tool_calls.append(tc)
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
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
