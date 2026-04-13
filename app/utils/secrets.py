"""Secret scrubbing — detect and redact credentials before they reach logs or memory.

Used by memory tools (memory_append, notes_write, health_log) and
BaseAgent._sanitize_for_memory() to prevent API keys, passwords, and
other credentials from leaking into agent files.

Usage:
    from app.utils.secrets import scrub
    clean_text = scrub("my key is sk-ant-abc123...")  # "my key is [REDACTED]"
"""

from __future__ import annotations

import re

_PATTERNS: list[re.Pattern[str]] = [
    # Anthropic API keys
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
    # OpenAI API keys
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    # OpenRouter keys
    re.compile(r"sk-or-v1-[a-zA-Z0-9]{20,}"),
    # Google API keys
    re.compile(r"AIza[a-zA-Z0-9_-]{30,}"),
    # Generic key=value patterns (password, api_key, secret, token)
    re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(?:api[_-]?key|apikey)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(?:secret|client_secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(?:access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*\S+"),
    # PEM private keys
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    # Connection strings with embedded credentials
    re.compile(r"(?i)(?:postgres|mysql|mongodb|redis)://\S+:\S+@\S+"),
]


def scrub(text: str) -> str:
    """Replace detected secrets in *text* with ``[REDACTED]``.

    Returns the cleaned string. If no secrets are found, returns
    the original string unchanged.
    """
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
