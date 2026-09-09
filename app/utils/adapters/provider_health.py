"""Phase 4C — remember which providers are out of credits, and stop retrying them.

The fallback chain already fails over correctly. What it did not do was
*remember*: a provider whose account is exhausted was re-attempted on every
single task, paying a full request round-trip to learn the same thing again.

Observed live: `OpenAI API error (429): You have no credits remaining`, with
OpenAI present in all 14 agents' fallback chains. Both the release gate and the
evaluator found this independently, from opposite directions.

## Why an API-key check cannot catch this

The OpenAI key IS set and IS valid. The account simply has no credits. Nothing
short of an actual request distinguishes "configured" from "usable", which is
why this has to be learned from responses rather than validated at startup.

## Exhausted is not the same as rate-limited

Both arrive as HTTP 429, and conflating them would be worse than doing nothing:
a rate limit clears in seconds, so benching that provider for half an hour would
turn a brief slowdown into a long outage. Only signals that mean *the account
cannot pay* set a cooldown; a bare 429 does not.

State is file-backed because agents run as separate processes, and a lesson
learned in one is worthless if the next process has to relearn it.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# How long a provider stays benched. Long enough to stop paying for repeated
# failures, short enough that topping up an account is picked up without anyone
# having to remember to clear state.
DEFAULT_COOLDOWN_S = 1800  # 30 minutes

# Substrings that mean "this account cannot currently pay", as opposed to
# "you are going too fast". Matched case-insensitively against the error text.
_EXHAUSTED_SIGNALS: tuple[str, ...] = (
    "no credits remaining",
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "billing_hard_limit_reached",
    "credit balance is too low",
    "payment required",
    "quota exceeded",
)

# Signals that are explicitly transient and must NOT bench a provider.
_TRANSIENT_SIGNALS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "please retry",
    "try again",
    "overloaded",
    "capacity",
)


def _state_path():
    from pathlib import Path

    from app.config import settings

    p = Path(settings.project_root) / "data" / "provider_health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _save(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass  # Health tracking must never break a request.


def classify_error(text: str) -> str:
    """Return 'exhausted', 'transient', or 'other' for a provider error string.

    Transient wins on a tie: mistaking a rate limit for an exhausted account
    benches a working provider, which is the more damaging error of the two.
    """
    lowered = (text or "").lower()
    if not lowered.strip():
        return "other"
    if any(s in lowered for s in _TRANSIENT_SIGNALS):
        return "transient"
    if any(s in lowered for s in _EXHAUSTED_SIGNALS):
        return "exhausted"
    return "other"


def record_error(adapter: str, error: BaseException | str) -> bool:
    """Bench ``adapter`` if the error means its account cannot pay.

    Returns True when a cooldown was started. Never raises.
    """
    try:
        text = str(error)
        if classify_error(text) != "exhausted":
            return False
        state = _load()
        state[adapter] = {
            "exhausted_at": time.time(),
            "reason": text[:200],
            "cooldown_s": DEFAULT_COOLDOWN_S,
        }
        _save(state)
        return True
    except Exception:
        return False


def is_exhausted(adapter: str, now: float | None = None) -> bool:
    """True while ``adapter`` is benched. Expired entries are treated as clear."""
    try:
        entry = _load().get(adapter)
        if not isinstance(entry, dict):
            return False
        elapsed = (now if now is not None else time.time()) - float(entry.get("exhausted_at", 0))
        return elapsed < float(entry.get("cooldown_s", DEFAULT_COOLDOWN_S))
    except Exception:
        return False


def record_success(adapter: str) -> None:
    """Clear a bench early — the account is demonstrably usable again."""
    try:
        state = _load()
        if state.pop(adapter, None) is not None:
            _save(state)
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    """Currently benched providers, for the dashboard and the release gate."""
    now = time.time()
    out: dict[str, Any] = {}
    for adapter, entry in _load().items():
        if not isinstance(entry, dict):
            continue
        remaining = float(entry.get("cooldown_s", DEFAULT_COOLDOWN_S)) - (
            now - float(entry.get("exhausted_at", 0))
        )
        if remaining > 0:
            out[adapter] = {
                "reason": entry.get("reason", ""),
                "seconds_remaining": int(remaining),
            }
    return out
