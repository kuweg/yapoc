"""Hardcoded security deny rules — the fast path for the security gate.

Layer 1 of the security gate. Pure synchronous classifier, no LLM call:
- Absolute self-destruction (modifying master/security, settings.py, .env, agent-settings.json)
- Absolute system-destruction (rm -rf /, dd if=, paths outside project_root)

Anything that's RISKY but doesn't match a hardcoded rule falls through as
``"ambiguous"`` and the caller (security_gate.classify) escalates to the
security agent LLM for classification.

Rules are deliberately conservative — false positives hurt less than false
negatives. Each rule documents its rationale via the `reason` field which
is surfaced to the caller and persisted to AUDIT.MD.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from app.config import settings


# Tools whose effects can damage YAPOC or the host. Anything else is allowed
# unconditionally (file_read, web_search, memory_append, etc. are free).
RISKY_TOOLS: frozenset[str] = frozenset({
    "file_delete",
    "shell_exec",
    "delete_agent",
    "update_agent_config",
    "agent_amnesia",
    "kill_agent",
    "update_config",
})

# Tools NOT in RISKY_TOOLS but with specific patterns we hard-deny anyway.
# Used to close the "ask builder to edit security/PROMPT.MD" loophole.
_PATTERN_DENY_TOOLS: frozenset[str] = frozenset({"file_write", "file_edit"})

# Core agents that must never be deleted/killed/amnesia'd/config-edited.
_CORE_AGENTS: frozenset[str] = frozenset({
    "master", "planning", "builder", "keeper", "doctor",
    "model_manager", "security", "evaluator",
})

# Critical config files anyone editing must NOT delete or sweep under
# `agents/security/`. Path SUFFIX match (so any project-relative form hits).
_CRITICAL_PATH_SUFFIXES: tuple[str, ...] = (
    ".env",
    "app/config/settings.py",
    "app/config/agent-settings.json",
    "app/agents/master/PROMPT.MD",
    "app/agents/security/PROMPT.MD",
)

# Substrings/regexes that flag a shell command as system-destruction.
_SHELL_DESTRUCTION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\brm\s+-rf\s+/(?:\s|$)"),       # rm -rf /
    re.compile(r"\brm\s+-rf\s+/[a-zA-Z]"),       # rm -rf /something at root
    re.compile(r"\brm\s+-rf\s+~"),               # rm -rf ~
    re.compile(r"\brm\s+-rf\s+\$HOME"),          # rm -rf $HOME
    re.compile(r"\bdd\s+if="),                   # dd if=
    re.compile(r"\bmkfs\."),                     # mkfs.ext4 etc.
    re.compile(r":\(\)\s*\{"),                   # fork bomb
    re.compile(r">\s*/dev/sd[a-z]"),             # write to a block device
    re.compile(r"\bchmod\s+-R?\s*000\s+/"),      # chmod 000 /
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b"),  # power ops
)


@dataclass(frozen=True)
class Rule:
    tool: str
    matcher: Callable[[dict], bool]
    reason: str
    category: Literal["self_destruction", "system_destruction"]


def _path_in_project(raw: str) -> bool:
    """Return True if raw resolves under settings.project_root."""
    try:
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = settings.project_root / target
        resolved = target.resolve()
        return str(resolved).startswith(str(settings.project_root.resolve()))
    except (OSError, ValueError):
        return False


def _has_critical_suffix(raw: str) -> bool:
    n = raw.replace("\\", "/").lstrip("./")
    return any(n.endswith(suf) for suf in _CRITICAL_PATH_SUFFIXES)


def _under_security_dir(raw: str) -> bool:
    norm = raw.replace("\\", "/")
    return "/agents/security/" in norm or norm.startswith("agents/security/") or "app/agents/security/" in norm


_ABS_PATH_TOKEN_RE = re.compile(
    r"(?:^|(?<=[\s|&;<>(\"']))(~|/)[^\s'\";|&<>()]+"
)


def _shell_escapes_project(command: str) -> bool:
    """Heuristic: command operates on an absolute path NOT under project_root.

    Matches TOKEN-START absolute paths only (so `app/agents` won't trigger on
    its embedded `/agents` substring). False positives still possible — that's
    fine: the LLM Layer-2 isn't invoked when this fires, but a human-CLI
    bypass still respects hardcoded rules. Tune up if it bites.
    """
    for match in _ABS_PATH_TOKEN_RE.finditer(command):
        token = match.group(0)
        if not _path_in_project(token):
            return True
    return False


# ── The actual deny list ─────────────────────────────────────────────────

HARDCODED_DENY: tuple[Rule, ...] = (
    # self-destruction: critical files
    Rule(
        tool="file_delete",
        matcher=lambda p: _has_critical_suffix(str(p.get("path", ""))),
        reason="deletion of core configuration / agent file",
        category="self_destruction",
    ),
    # self-destruction: core agents
    Rule(
        tool="delete_agent",
        matcher=lambda p: str(p.get("name", "")) in _CORE_AGENTS,
        reason="deletion of core agent",
        category="self_destruction",
    ),
    Rule(
        tool="kill_agent",
        matcher=lambda p: str(p.get("agent_name", p.get("name", ""))) in {"master", "security"},
        reason="kill of core orchestration agent",
        category="self_destruction",
    ),
    Rule(
        tool="update_agent_config",
        matcher=lambda p: str(p.get("name", p.get("agent_name", ""))) in {"master", "security"},
        reason="config edit of master/security agent",
        category="self_destruction",
    ),
    Rule(
        tool="agent_amnesia",
        matcher=lambda p: str(p.get("name", p.get("agent_name", ""))) in {"master", "security"},
        reason="memory wipe of master/security agent",
        category="self_destruction",
    ),
    Rule(
        tool="update_config",
        matcher=lambda p: any(_under_security_dir(str(v)) for v in p.values() if isinstance(v, str)),
        reason="self-config edit referencing security dir",
        category="self_destruction",
    ),
    # cross-tool loophole closure: writing under security dir via file_write/file_edit
    Rule(
        tool="file_write",
        matcher=lambda p: _under_security_dir(str(p.get("path", ""))),
        reason="write into security agent directory",
        category="self_destruction",
    ),
    Rule(
        tool="file_edit",
        matcher=lambda p: _under_security_dir(str(p.get("path", ""))),
        reason="edit of security agent file",
        category="self_destruction",
    ),
    # cross-tool loophole closure: writing core config files
    Rule(
        tool="file_write",
        matcher=lambda p: _has_critical_suffix(str(p.get("path", ""))),
        reason="write to core configuration file",
        category="self_destruction",
    ),
    Rule(
        tool="file_edit",
        matcher=lambda p: _has_critical_suffix(str(p.get("path", ""))),
        reason="edit of core configuration file",
        category="self_destruction",
    ),
    # system-destruction: shell command patterns
    Rule(
        tool="shell_exec",
        matcher=lambda p: any(pat.search(str(p.get("command", ""))) for pat in _SHELL_DESTRUCTION_PATTERNS),
        reason="destructive shell pattern (rm -rf, dd, mkfs, fork bomb, etc.)",
        category="system_destruction",
    ),
    Rule(
        tool="shell_exec",
        matcher=lambda p: _shell_escapes_project(str(p.get("command", ""))),
        reason="shell command targets paths outside project_root",
        category="system_destruction",
    ),
    # system-destruction: file_delete outside project_root
    Rule(
        tool="file_delete",
        matcher=lambda p: not _path_in_project(str(p.get("path", ""))),
        reason="file_delete targets path outside project_root",
        category="system_destruction",
    ),
)


def hardcoded_check(
    tool: str, params: dict
) -> tuple[Literal["allow", "deny", "ambiguous"], str]:
    """Layer-1 classifier. Returns (decision, reason).

    - ``"allow"`` — tool not risky / no rule matched and tool is not in RISKY_TOOLS
    - ``"deny"`` — a hardcoded rule fired; ``reason`` describes which
    - ``"ambiguous"`` — tool IS risky but no hardcoded rule fired; caller
       should escalate to the security agent LLM for further classification
    """
    if tool not in RISKY_TOOLS and tool not in _PATTERN_DENY_TOOLS:
        return "allow", ""

    for rule in HARDCODED_DENY:
        if rule.tool != tool:
            continue
        try:
            matched = rule.matcher(params)
        except Exception:
            # Defensive — a broken matcher should NEVER allow risky ops through.
            # Treat exception as ambiguous so the LLM layer can review.
            continue
        if matched:
            return "deny", f"{rule.category}: {rule.reason}"

    if tool in RISKY_TOOLS:
        return "ambiguous", ""
    return "allow", ""
