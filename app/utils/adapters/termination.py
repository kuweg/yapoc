"""Provider termination validation shared by streaming adapters."""
import json


def require_complete(reason: str | None) -> None:
    # 'length' means the model reached its max output tokens — the content
    # generated up to that point is valid and usable, so do NOT treat it as a
    # corrupt stream. (DeepSeek/OpenAI both use this as a normal terminal reason.)
    if reason not in {'stop', 'end_turn', 'tool_calls', 'tool_use', 'function_call', 'completed', 'STOP', 'length'}:
        raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')


def _repair_truncated_json(raw: str) -> str | None:
    """Attempt to repair a JSON string that was truncated mid-stream.

    Streaming adapters accumulate tool-call arguments incrementally; when a
    provider hits its max output tokens mid-tool-call, the argument JSON is cut
    off (unterminated string and/or unbalanced brackets). Recover the common
    truncation shapes by closing the open string and balancing the bracket stack.

    Returns repaired JSON text, or None if the input was not a string worth
    attempting (empty / already well-formed / structurally unfixable).
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None

    stack: list[str] = []
    in_string = False
    escape = False
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch in '}]':
                if stack and stack[-1] == ch:
                    stack.pop()
                else:
                    # Mismatched closer — structurally unfixable.
                    return None

    repaired = s
    if in_string:
        if escape:
            # Dangling backslash would escape the closing quote; drop it first.
            repaired = repaired[:-1]
        repaired += '"'
    for closer in reversed(stack):
        repaired += closer

    return repaired if repaired != s else None


def parse_tool_arguments(raw: str | dict) -> dict:
    arguments: object
    if isinstance(raw, str):
        try:
            arguments = json.loads(raw)
        except (ValueError, TypeError):
            # Retry once on truncated tool-argument JSON (provider hit its output
            # cap mid-tool-call). Recover the common truncation shapes before
            # giving up.
            repaired = _repair_truncated_json(raw)
            if repaired is not None:
                try:
                    arguments = json.loads(repaired)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError('Incomplete provider response: invalid tool argument JSON') from exc
            else:
                raise RuntimeError('Incomplete provider response: invalid tool argument JSON')
    else:
        arguments = raw

    if not isinstance(arguments, dict):
        raise RuntimeError('Invalid provider response: tool arguments must be an object')
    return arguments
