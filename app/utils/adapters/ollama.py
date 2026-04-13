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
from .normalize import normalize_to_ollama

_DEFAULT_CONTEXT_WINDOW = 32_768


class OllamaAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._chat_url = f"{settings.ollama_base_url}/api/chat"

    def context_window_size(self) -> int:
        return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)

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
            "stream": False,
            "options": {"temperature": self._config.temperature},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self._chat_url, json=payload, timeout=300)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._config.model,
            "messages": self._build_messages(system_prompt, user_message, history),
            "stream": True,
            "options": {"temperature": self._config.temperature},
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", self._chat_url, json=payload, timeout=300
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        if content := chunk.get("message", {}).get("content", ""):
                            yield content

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        # Convert Anthropic-format messages to Ollama format
        ollama_messages = [{"role": "system", "content": system_prompt}]
        ollama_messages.extend(normalize_to_ollama(messages))

        ollama_tools = [
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
            "messages": ollama_messages,
            "stream": True,
            "options": {"temperature": self._config.temperature},
        }
        if ollama_tools:
            payload["tools"] = ollama_tools

        t_start = time.perf_counter()
        all_tool_calls: list[dict[str, Any]] = []
        prompt_eval_count = 0
        eval_count = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", self._chat_url, json=payload, timeout=300
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    message = chunk.get("message", {})

                    # Text content
                    if content := message.get("content", ""):
                        yield TextDelta(content)

                    # Tool calls — Ollama returns full tool_calls in message (not delta)
                    if tc_list := message.get("tool_calls"):
                        all_tool_calls.extend(tc_list)

                    # Usage stats from final chunk (done=true)
                    if chunk.get("done"):
                        prompt_eval_count = chunk.get("prompt_eval_count", 0)
                        eval_count = chunk.get("eval_count", 0)

        elapsed = time.perf_counter() - t_start

        # Build tool calls and assistant_content
        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []

        for i, tc_data in enumerate(all_tool_calls):
            func = tc_data.get("function", {})
            name = func.get("name", "")
            arguments = func.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            tc_id = f"call_{i}"
            tc = ToolCall(id=tc_id, name=name, input=arguments)
            tool_calls.append(tc)
            assistant_content.append({
                "type": "tool_use",
                "id": tc_id,
                "name": name,
                "input": arguments,
            })
            yield ToolStart(name=name, input=arguments)

        # Emit usage stats
        tps = eval_count / elapsed if elapsed > 0 else 0.0
        yield UsageStats(
            input_tokens=prompt_eval_count,
            output_tokens=eval_count,
            tokens_per_second=tps,
            context_window=self.context_window_size(),
        )

        stop_reason = "tool_use" if tool_calls else "end_turn"
        yield TurnComplete(
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
        )
