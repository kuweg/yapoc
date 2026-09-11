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
from pathlib import Path


def credential_path(path: str | Path) -> bool:
    """Credential stores must not be exposed by generic file/execution tools."""
    parts = Path(path).parts
    for part in parts:
        name = part.lower()
        if (name.startswith('.env') and name != '.env.example') or name in {
            '.git', '.ssh', '.aws', '.azure', '.kube', '.gnupg', '.credentials',
            'credentials', 'credentials.json', 'token.json', 'tokens.json',
            '.netrc', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519',
        }:
            return True
        if name.endswith(('.pem', '.key', '.p12', '.pfx')) or (
            name.endswith('.json') and any(word in name for word in ('token', 'credential', 'client_secret'))
        ):
            return True
    return False

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)'),
    re.compile(r'(?i)\b[A-Z0-9_]*TOKEN\s*[:=]\s*\S+'),
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
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----|\Z)"),
    # Connection strings with embedded credentials
    re.compile(r"(?i)(?:postgres|mysql|mongodb|redis)://\S+:\S+@\S+"),
]


def scrub(text: str) -> str:
    """Replace detected secrets in *text* with ``[REDACTED]``.

    Returns the cleaned string. If no secrets are found, returns
    the original string unchanged.
    """
    result = text
    # Import lazily: settings initialization must not depend on this module.
    from app.config import settings
    from pydantic import SecretStr
    from urllib.parse import quote
    import base64
    for name in type(settings).model_fields:
        value = getattr(settings, name)
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        elif not any(word in name for word in ('api_key', 'token', 'secret', 'password')):
            continue
        if isinstance(value, str) and value:
            for variant in (value, quote(value, safe=''), base64.b64encode(value.encode()).decode()):
                result = result.replace(variant, '[REDACTED]')
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


# ── PII patterns ──────────────────────────────────────────────────────────────

_PII_PATTERNS: list[re.Pattern[str]] = [
    # Email addresses
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    # US phone numbers
    re.compile(r"\b(?:\+1[-.]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    # Credit card numbers (4 groups of 4 digits)
    re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    # US Social Security Numbers
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]


def scrub_pii(text: str) -> str:
    """Replace both secrets and PII in *text* with ``[REDACTED]``.

    Applies all secret patterns from :func:`scrub` plus additional PII
    patterns (email, phone, credit card, SSN). Use this for data files
    that may contain personal information.
    """
    result = scrub(text)
    for pattern in _PII_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
