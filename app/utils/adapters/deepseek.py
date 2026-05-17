"""DeepSeek adapter — OpenAI-compatible API.

DeepSeek exposes an OpenAI-compatible chat/completions endpoint,
so this adapter reuses the same logic as OpenAIAdapter with a
different base URL and API key.
"""

import asyncio
import json
import logging
import re
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
    ThinkingDelta,
    ToolCall,
    ToolDefinition,
    ToolStart,
    TurnComplete,
    UsageStats,
)
from .models import ALL_CONTEXT_WINDOWS

log = logging.getLogger(__name__)

_DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

_DEFAULT_CONTEXT_WINDOW = 64_000


def _supports_reasoning_replay(model_id: str) -> bool:
    """Whether assistant reasoning_content can be replayed in input messages."""
    normalized = model_id.lower()
    if "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    # deepseek-reasoner explicitly rejects reasoning_content in inputs.
    return normalized != "deepseek-reasoner"


def _normalize_to_deepseek(
    messages: list[dict[str, Any]],
    *,
    include_reasoning_content: bool,
) -> list[dict[str, Any]]:
    """Convert Anthropic-style history to DeepSeek's chat-completions shape.

    This mirrors normalize_to_openai() but preserves assistant reasoning blocks
    as ``reasoning_content`` for models that require replay in thinking mode.
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
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
                elif btype == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking:
                        reasoning_parts.append(thinking)
                elif btype == "reasoning":
                    reasoning = block.get("text", block.get("reasoning", ""))
                    if reasoning:
                        reasoning_parts.append(reasoning)
                else:
                    text_parts.append(str(block))

            out: dict[str, Any] = {"role": "assistant"}
            combined_text = "\n".join(t for t in text_parts if t)
            out["content"] = combined_text or None
            if tool_calls:
                out["tool_calls"] = tool_calls
            if include_reasoning_content and reasoning_parts:
                out["reasoning_content"] = "\n".join(t for t in reasoning_parts if t)
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
                        "tool_call_id": block["tool_use_id"],
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


def _raise_with_detail(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
        detail = body.get("error", {}).get("message", response.text)
    except Exception:
        detail = response.text
    raise httpx.HTTPStatusError(
        f"DeepSeek API error ({response.status_code}): {detail}",
        request=response.request,
        response=response,
    )


def _parse_raw_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse raw XML tool calls from DeepSeek V4 models.

    Handles two formats:
    1. <invoke name="func_name"><parameter name="x">val</parameter></invoke>
    2. <functioncall><invoke name="func_name"><parameter name="x" string="true">val</parameter></invoke></functioncall>
    3. <functioncall>func_name({"x": "val"})</functioncall>
    """
    tool_calls: list[dict[str, Any]] = []

    # Format 1 & 2: <invoke name="...">...</invoke>
    for match in re.finditer(r'<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>', text, re.DOTALL):
        name = match.group(1)
        params_xml = match.group(2)
        params: dict[str, Any] = {}
        for p in re.finditer(r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>', params_xml, re.DOTALL):
            param_name = p.group(1)
            param_val = p.group(2).strip()
            # Try to parse as JSON
            try:
                params[param_name] = json.loads(param_val)
            except (json.JSONDecodeError, TypeError):
                params[param_name] = param_val
        tool_calls.append({"name": name, "input": params})

    # Format 3: <functioncall>name({"key": "val"})</functioncall>
    for match in re.finditer(
        r'<functioncall>(?:<invoke[^>]*>)?\s*(\w+)\s*\(\s*(.*?)\s*\)\s*(?:</invoke>)?</functioncall>',
        text,
        re.DOTALL,
    ):
        name = match.group(1)
        args_str = match.group(2)
        try:
            params = json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            params = {}
        tool_calls.append({"name": name, "input": params})

    # Format 4: Self-closing tags like <tool_name param="value" />
    _structural_tags = frozenset({
        "br", "hr", "img", "input", "meta", "link", "area", "base", "col",
        "embed", "source", "track", "wbr", "param", "command", "keygen",
    })
    for match in re.finditer(
        r'<(\w+)\s+([^>/]+?)\s*/>',
        text,
        re.DOTALL,
    ):
        name = match.group(1)
        attrs_str = match.group(2)
        if name in _structural_tags:
            continue
        params: dict[str, Any] = {}
        for a in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', attrs_str):
            param_name = a.group(1)
            param_val = a.group(2).strip()
            try:
                params[param_name] = json.loads(param_val)
            except (json.JSONDecodeError, TypeError):
                params[param_name] = param_val
        tool_calls.append({"name": name, "input": params})

    # Format 5: <function_name><param_name>value</param_name></function_name>
    # DeepSeek V4 Pro outputs tool calls where the function name IS the XML element.
    # Known structural tags to skip (already handled or non-functional).
    structural = frozenset({
        "invoke", "functioncall", "function", "parameter",
        "tool_calls", "tool_use", "thinking", "reasoning",
        "content", "input", "result", "output", "error",
    })
    for match in re.finditer(
        r'<(\w+)>((?:\s*<\w+>[^<]*</\w+>\s*)*)</\1>',
        text,
        re.DOTALL,
    ):
        outer_tag = match.group(1)
        if outer_tag in structural:
            continue
        inner = match.group(2)
        params: dict[str, Any] = {}
        for p in re.finditer(r'<(\w+)>([^<]*)</\1>', inner, re.DOTALL):
            param_name = p.group(1)
            param_val = p.group(2).strip()
            try:
                params[param_name] = json.loads(param_val)
            except (json.JSONDecodeError, TypeError):
                params[param_name] = param_val
        if params:
            tool_calls.append({"name": outer_tag, "input": params})
        else:
            # Treat the entire inner text as the argument
            tool_calls.append({"name": outer_tag, "input": {"value": inner.strip()}})

    return tool_calls


class DeepSeekAdapter(BaseLLMAdapter):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self._api_key = settings.deepseek_api_key
        if not self._api_key:
            raise ValueError(
                "DeepSeek API key is not set. "
                "Set DEEPSEEK_API_KEY in your .env file or environment."
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
                _DEEPSEEK_API_URL,
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
                _DEEPSEEK_API_URL,
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
        include_reasoning_content = _supports_reasoning_replay(self._config.model)
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(
            _normalize_to_deepseek(
                messages,
                include_reasoning_content=include_reasoning_content,
            )
        )

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
        reasoning_parts: list[str] = []
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                _DEEPSEEK_API_URL,
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

                    if chunk.get("usage"):
                        usage = chunk["usage"]
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    if reasoning := delta.get("reasoning_content"):
                        reasoning_parts.append(reasoning)
                        yield ThinkingDelta(reasoning)

                    if text := delta.get("content"):
                        text_parts.append(text)
                        yield TextDelta(text)

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

        # Check for raw XML tool calls that weren't captured as structured tool_calls
        raw_xml = "".join(text_parts)
        parsed_tool_calls = _parse_raw_tool_calls(raw_xml)

        elapsed = time.perf_counter() - t_start

        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []

        # If raw XML tool calls were parsed, use those instead of text_parts
        if parsed_tool_calls:
            # Clear text_parts since the XML was tool calls, not actual text
            text_parts.clear()
            for tc in parsed_tool_calls:
                tc_id = f"call_{int(time.time() * 1000)}_{len(tool_calls)}"
                tc_obj = ToolCall(id=tc_id, name=tc["name"], input=tc["input"])
                tool_calls.append(tc_obj)
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc_id,
                    "name": tc["name"],
                    "input": tc["input"],
                })
                yield ToolStart(name=tc["name"], input=tc["input"])

        if include_reasoning_content and reasoning_parts:
            assistant_content.append(
                {"type": "reasoning", "text": "".join(reasoning_parts)}
            )
        if text_parts:
            assistant_content.append(
                {"type": "text", "text": "".join(text_parts)}
            )

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
