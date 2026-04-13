"""Shared message normalization: Anthropic format → OpenAI / Ollama format.

BaseAgent builds messages in Anthropic format (tool_use / tool_result content blocks).
Non-Anthropic adapters must convert before sending to their respective APIs.
"""

from __future__ import annotations

import json
from typing import Any


def normalize_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to OpenAI chat-completions format.

    Handles:
    - assistant messages with tool_use blocks → assistant with tool_calls
    - user messages with tool_result blocks → separate role=tool messages
    - plain text messages pass through unchanged
    """
    result: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Plain string content — pass through
        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        # List content — check for Anthropic tool blocks
        if not isinstance(content, list):
            result.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            # May contain text + tool_use blocks
            text_parts: list[str] = []
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

            out: dict[str, Any] = {"role": "assistant"}
            combined_text = "\n".join(t for t in text_parts if t)
            if combined_text:
                out["content"] = combined_text
            else:
                out["content"] = None
            if tool_calls:
                out["tool_calls"] = tool_calls
            result.append(out)

        elif role == "user":
            # May contain tool_result blocks (from BaseAgent tool execution)
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

            # Emit text parts as a user message if any
            combined = "\n".join(t for t in text_parts_user if t)
            if combined:
                result.append({"role": "user", "content": combined})

            # Emit each tool result as a separate message
            result.extend(tool_results)

        else:
            # system or other roles — pass through
            result.append({"role": role, "content": str(content) if not isinstance(content, str) else content})

    return result


def normalize_to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to Ollama chat format.

    Ollama uses a similar format to OpenAI for tool results (role=tool),
    but tool_calls are embedded differently in assistant messages.
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
                        "function": {
                            "name": block["name"],
                            "arguments": block.get("input", {}),
                        },
                    })

            out: dict[str, Any] = {"role": "assistant"}
            combined_text = "\n".join(t for t in text_parts if t)
            out["content"] = combined_text or ""
            if tool_calls:
                out["tool_calls"] = tool_calls
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
            result.append({"role": role, "content": str(content) if not isinstance(content, str) else content})

    return result
