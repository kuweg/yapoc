"""Provider termination validation shared by streaming adapters."""
import json


def require_complete(reason: str | None) -> None:
    if reason not in {'stop', 'end_turn', 'tool_calls', 'tool_use', 'function_call', 'completed', 'STOP'}:
        raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')


def parse_tool_arguments(raw: str | dict) -> dict:
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Incomplete provider response: invalid tool argument JSON') from exc
    if not isinstance(arguments, dict):
        raise RuntimeError('Invalid provider response: tool arguments must be an object')
    return arguments
