"""Security gate — classifies risky tool calls before they execute.

Two-layer design:
  Layer 1 (hardcoded, sync): ``security_policy.hardcoded_check`` — instant
          deny for absolute self/system-destruction (rm -rf /, delete master,
          etc.) and instant allow for non-risky tools.
  Layer 2 (LLM): when Layer 1 returns ``"ambiguous"``, the security agent's
          adapter is invoked with a strict JSON contract to classify the
          action. Result is cached for 60s by (tool, params-hash, caller).

The agent's tool-execution loop (``BaseAgent._execute_tool``) calls
``classify()`` before invoking the tool. On ``decision == "deny"`` it
short-circuits with an error-shaped result; the LLM sees the block reason
and decides what to do next.

Every decision — hardcoded or LLM-classified — is appended to
``app/agents/security/AUDIT.MD`` for forensics.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger as _log

from app.config import settings
from app.utils.tools.security_policy import hardcoded_check, RISKY_TOOLS


_CACHE_TTL = 60.0  # seconds
_CACHE: dict[tuple[str, str, str], tuple[float, str, str]] = {}
_CACHE_LOCK = asyncio.Lock()

_AUDIT_PATH = settings.agents_dir / "security" / "AUDIT.MD"


def _hash_params(params: dict) -> str:
    try:
        payload = json.dumps(params, sort_keys=True, default=str)
    except Exception:
        payload = repr(sorted(params.items())) if hasattr(params, "items") else repr(params)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _truncate(s: str, n: int = 120) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def _append_audit(
    *,
    caller: str,
    tool: str,
    params: dict,
    decision: str,
    reason: str,
    source: Literal["hardcoded", "llm", "bypass"],
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        params_str = json.dumps(params, default=str)
    except Exception:
        params_str = repr(params)
    line = (
        f"[{ts}] caller={caller} tool={tool} source={source} "
        f"decision={decision} reason={reason!r} params={_truncate(params_str, 160)}\n"
    )
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _log.warning("security_gate: failed to append AUDIT.MD ({})", exc)


async def _classify_via_llm(tool: str, params: dict, caller: str) -> tuple[str, str]:
    """One-shot consult of the security agent's adapter. Returns (decision, reason).

    Does NOT spawn the agent as a subprocess — instantiates the adapter
    directly and calls ``complete()`` with the security-agent system prompt
    + a single user message containing the action payload.
    """
    # Local import to avoid any chance of cycles at module import time.
    from app.agents.security import security_agent

    cfg = await security_agent._load_config()
    adapter = await security_agent._load_adapter(cfg)
    system_prompt = await security_agent._read_file("PROMPT.MD")
    if not system_prompt.strip():
        return "deny", "security agent PROMPT.MD missing — failing safe"

    payload = {
        "tool": tool,
        "params": params,
        "caller": caller,
        "context": "",
    }
    user_msg = json.dumps(payload, default=str)

    try:
        raw = await adapter.complete(
            system_prompt=system_prompt,
            user_message=user_msg,
        )
    except Exception as exc:
        # Provider error → fail SAFE (allow). Logging-wise this is rare; the
        # LLM layer is only hit on ambiguous-but-not-hardcoded-deny cases,
        # and a provider outage shouldn't strand the autonomous loop.
        # Hardcoded rules still block the truly dangerous cases.
        _log.warning("security_gate: LLM consult failed ({}) — defaulting to allow", exc)
        return "allow", f"llm-unavailable: {type(exc).__name__}"

    # Find the first {...} JSON object in the response.
    raw_stripped = raw.strip()
    start = raw_stripped.find("{")
    end = raw_stripped.rfind("}")
    if start < 0 or end < 0 or end < start:
        return "deny", f"security-agent output not JSON: {_truncate(raw_stripped, 80)}"

    try:
        obj = json.loads(raw_stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        return "deny", f"security-agent JSON parse failed: {exc}"

    decision = str(obj.get("decision", "")).lower()
    reason = str(obj.get("reason", ""))[:200]
    if decision not in {"allow", "deny"}:
        return "deny", f"security-agent invalid decision={decision!r}"
    return decision, reason


async def classify(tool: str, params: dict, caller: str) -> tuple[str, str]:
    """Single entry point for the tool-loop hook. Returns (decision, reason).

    decision ∈ {"allow", "deny"}.
    Always audits to AUDIT.MD before returning.
    """
    # ── Recursion guard ────────────────────────────────────────────────
    # The security agent never invokes tools (its CONFIG.yaml has tools: []),
    # but if some future change gives it any, we bypass the gate to avoid
    # infinite consultation loops.
    if caller == "security":
        _append_audit(
            caller=caller, tool=tool, params=params,
            decision="allow", reason="caller=security (gate bypass)",
            source="bypass",
        )
        return "allow", "caller=security"

    # ── Layer 1: hardcoded ──────────────────────────────────────────────
    decision, reason = hardcoded_check(tool, params)
    if decision in ("allow", "deny"):
        _append_audit(
            caller=caller, tool=tool, params=params,
            decision=decision, reason=reason or "non-risky tool",
            source="hardcoded",
        )
        return decision, reason or "ok"

    # ── Layer 2: LLM ────────────────────────────────────────────────────
    # decision == "ambiguous" — risky tool but no hardcoded rule fired.
    cache_key = (tool, _hash_params(params), caller)
    now = time.monotonic()
    async with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            _, cd, cr = cached
            _append_audit(
                caller=caller, tool=tool, params=params,
                decision=cd, reason=cr, source="llm",
            )
            return cd, cr

    decision, reason = await _classify_via_llm(tool, params, caller)
    async with _CACHE_LOCK:
        _CACHE[cache_key] = (now, decision, reason)
    _append_audit(
        caller=caller, tool=tool, params=params,
        decision=decision, reason=reason, source="llm",
    )
    return decision, reason


def cache_clear() -> None:
    """Test helper — drop the in-process classifier cache."""
    _CACHE.clear()
