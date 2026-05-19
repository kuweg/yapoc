"""Google Gemini adapter using the native google-genai SDK."""

import time
from typing import Any, AsyncIterator

from google import genai
from google.genai import types

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

_DEFAULT_CONTEXT_WINDOW = 1_000_000


class GoogleAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        api_key = settings.google_api_key
        if not api_key:
            raise ValueError(
                "Google API key is not set. "
                "Set GOOGLE_API_KEY in your .env file or environment."
            )
        self._client = genai.Client(api_key=api_key)

    def context_window_size(self) -> int:
        return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)

    # ── Message conversion ───────────────────────────────────────────────────

    @staticmethod
    def _role_to_gemini(role: str) -> str:
        return "model" if role == "assistant" else role

    @staticmethod
    def _messages_to_contents(
        messages: list[dict[str, Any]],
    ) -> list[types.Content]:
        tool_names: dict[str, str] = {}
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_names[block["id"]] = block.get("name", "")

        contents: list[types.Content] = []
        for msg in messages:
            role = msg["role"]
            gemini_role = "model" if role == "assistant" else role
            content = msg.get("content", "")
            parts: list[types.Part] = []

            if isinstance(content, str):
                if content:
                    parts.append(types.Part(text=content))
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        parts.append(types.Part(text=str(block)))
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        text = block.get("text", "")
                        if text:
                            parts.append(types.Part(text=text))
                    elif btype == "thinking":
                        pass
                    elif btype == "tool_use":
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=block["id"],
                                    name=block["name"],
                                    args=block.get("input", {}),
                                )
                            )
                        )
                    elif btype == "tool_result":
                        tool_use_id = block["tool_use_id"]
                        name = tool_names.get(tool_use_id, "")
                        parts.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=tool_use_id,
                                    name=name,
                                    response={"result": block.get("content", "")},
                                )
                            )
                        )

            if parts:
                contents.append(types.Content(role=gemini_role, parts=parts))

        return contents

    # ── API methods ──────────────────────────────────────────────────────────

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
        mime: str | None = None
        if effective == "json":
            if _supports_native_json(self._config.model):
                mime = "application/json"
            else:
                sp = _apply_json_nudge(system_prompt)

        contents: list[types.Content] = []
        for msg in history or []:
            role = self._role_to_gemini(msg.role)
            if msg.content:
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=msg.content)])
                )
        contents.append(
            types.Content(role="user", parts=[types.Part(text=user_message)])
        )

        config_kwargs: dict[str, Any] = {
            "system_instruction": sp,
            "temperature": self._config.temperature,
            "max_output_tokens": self._config.max_tokens,
        }
        if mime is not None:
            config_kwargs["response_mime_type"] = mime
        config = types.GenerateContentConfig(**config_kwargs)

        response = await self._client.aio.models.generate_content(
            model=self._config.model,
            contents=contents,
            config=config,
        )
        return response.text or ""

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        contents: list[types.Content] = []
        for msg in history or []:
            role = self._role_to_gemini(msg.role)
            if msg.content:
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=msg.content)])
                )
        contents.append(
            types.Content(role="user", parts=[types.Part(text=user_message)])
        )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_tokens,
        )

        # google-genai 2.x: `generate_content_stream` is an `async def` that
        # returns an AsyncIterator. We must `await` the call to get the
        # iterator before driving it with `async for`. Direct
        # `async for x in client.aio.models.generate_content_stream(...)`
        # raises TypeError: 'async for' requires an object with __aiter__,
        # got coroutine.
        stream = await self._client.aio.models.generate_content_stream(
            model=self._config.model,
            contents=contents,
            config=config,
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        gemini_contents = self._messages_to_contents(messages)

        gemini_tools = None
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=t.input_schema,
                )
                for t in tools
            ]
            gemini_tools = [types.Tool(function_declarations=declarations)]

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_tokens,
            tools=gemini_tools,
        )

        if settings.enable_thinking:
            config.thinking_config = types.ThinkingConfig(
                thinking_level="LOW",
                thinking_budget=settings.thinking_budget_tokens,
            )

        t_start = time.perf_counter()
        input_tokens = 0
        output_tokens = 0
        seen_call_ids: set[str] = set()
        tool_calls: list[ToolCall] = []
        assistant_text_parts: list[str] = []

        # See identical fix in `stream()` above — `generate_content_stream`
        # is a coroutine in google-genai 2.x; await it before iterating.
        stream = await self._client.aio.models.generate_content_stream(
            model=self._config.model,
            contents=gemini_contents,
            config=config,
        )
        async for chunk in stream:
            if chunk.text:
                assistant_text_parts.append(chunk.text)
                yield TextDelta(chunk.text)

            if chunk.function_calls:
                for fc in chunk.function_calls:
                    if fc.id and fc.id not in seen_call_ids:
                        seen_call_ids.add(fc.id)
                        args = fc.args if isinstance(fc.args, dict) else {}
                        tc = ToolCall(id=fc.id, name=fc.name or "", input=args)
                        tool_calls.append(tc)
                        yield ToolStart(name=tc.name, input=tc.input)

            if chunk.usage_metadata:
                input_tokens = chunk.usage_metadata.prompt_token_count or 0
                output_tokens = chunk.usage_metadata.candidates_token_count or 0

        elapsed = time.perf_counter() - t_start
        tps = output_tokens / elapsed if elapsed > 0 else 0.0

        yield UsageStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_per_second=tps,
            context_window=self.context_window_size(),
        )

        assistant_content: list[dict[str, Any]] = []
        combined_text = "".join(assistant_text_parts).strip()
        if combined_text:
            assistant_content.append({"type": "text", "text": combined_text})
        for tc in tool_calls:
            assistant_content.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )

        stop_reason = "tool_use" if tool_calls else "end_turn"
        yield TurnComplete(
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
        )
