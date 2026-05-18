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


@dataclass(frozen=True)
class AllowRule:
    """Caller-aware allow rule. Checked AFTER deny rules — deny wins on conflict.

    Lets us grant specific agents authority over specific tools without
    routing every call through the LLM classifier. E.g. master is the
    natural authority for ``kill_agent`` (recovering stuck sub-agents is
    routine ops); keeper is the natural authority for ``update_agent_config``
    and edits to ``agent-settings.json`` (keeper IS the config manager).

    matcher receives ``(caller, params)`` so the rule can gate on both
    who's calling and what they're trying to do.
    """
    tool: str
    matcher: Callable[[str, dict], bool]
    reason: str


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

# Safe absolute paths that legitimate shell commands routinely reference,
# even though they're outside project_root. Without this whitelist, every
# `curl -o /dev/null`, `>/dev/stderr`, `read < /dev/tty`, etc. would trip
# system-destruction — observed live blocking builder's localhost curl
# tests during the OpenAI voiceover end-to-end test.
_SAFE_ABS_PATH_PREFIXES: tuple[str, ...] = (
    "/dev/null",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/tty",
    "/dev/zero",
    "/dev/random",
    "/dev/urandom",
)


def _shell_escapes_project(command: str) -> bool:
    """Heuristic: command operates on an absolute path NOT under project_root.

    Matches TOKEN-START absolute paths only (so `app/agents` won't trigger on
    its embedded `/agents` substring). Common safe paths (``/dev/null``, etc.)
    are explicitly whitelisted — without that, ``curl -o /dev/null`` and
    similar harmless redirections trip the rule, blocking routine ops like
    smoke-testing an HTTP endpoint.

    False positives still possible — that's fine: the LLM Layer-2 isn't
    invoked when this fires, but a human-CLI bypass still respects hardcoded
    rules. Tune up if it bites.
    """
    for match in _ABS_PATH_TOKEN_RE.finditer(command):
        token = match.group(0)
        if any(token == p or token.startswith(p + "/") for p in _SAFE_ABS_PATH_PREFIXES):
            continue
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


# ── Caller-aware allow rules ────────────────────────────────────────────
#
# Some agents have legitimate authority over otherwise-risky tools. Routing
# those calls through the LLM classifier wastes tokens and creates the
# stuck-in-recovery-loop problem master kept hitting (master tries to fix
# config → blocked → delegates to keeper → keeper blocked → loops). The
# fix: hardcoded fast-path allow for the natural authorities.
#
# DENY rules above ALWAYS win over ALLOW — so target=master/security stays
# protected even when called by a blessed caller. Defense in depth.

def _is_agent_settings_json(path: str) -> bool:
    n = path.replace("\\", "/")
    return n.endswith("app/config/agent-settings.json") or n.endswith("config/agent-settings.json")


def _target_is_core_protected(params: dict) -> bool:
    """True if the param target is master or security — those stay protected
    even for blessed callers. Picked up by `kill_agent` / `update_agent_config`
    allow matchers as a safety conjunction."""
    target = str(params.get("name", "") or params.get("agent_name", ""))
    return target in {"master", "security"}


HARDCODED_ALLOW: tuple[AllowRule, ...] = (
    # Master is the orchestrator — killing a stuck sub-agent is routine
    # recovery work. Hardcoded-deny for target=master/security still wins.
    AllowRule(
        tool="kill_agent",
        matcher=lambda caller, p: caller == "master" and not _target_is_core_protected(p),
        reason="master has kill authority over non-core agents",
    ),
    AllowRule(
        tool="delete_agent",
        matcher=lambda caller, p: caller == "master" and str(p.get("name", "")) not in _CORE_AGENTS,
        reason="master has delete-agent authority over non-core agents",
    ),
    # Keeper IS the config manager. It needs to edit agent configs without
    # an LLM round-trip per call. Hardcoded-deny for target=master/security
    # still wins.
    AllowRule(
        tool="update_agent_config",
        matcher=lambda caller, p: caller == "keeper" and not _target_is_core_protected(p),
        reason="keeper has config-edit authority over non-core agents",
    ),
    # Keeper also needs to edit app/config/agent-settings.json directly
    # (it's the registry of agent → adapter/model bindings). Without this,
    # adding a tool to an agent's list requires hand-editing the file
    # outside the agent system — defeats the point of having a keeper.
    AllowRule(
        tool="file_edit",
        matcher=lambda caller, p: caller == "keeper" and _is_agent_settings_json(str(p.get("path", ""))),
        reason="keeper has edit authority over agent-settings.json",
    ),
    AllowRule(
        tool="file_write",
        matcher=lambda caller, p: caller == "keeper" and _is_agent_settings_json(str(p.get("path", ""))),
        reason="keeper has write authority over agent-settings.json",
    ),
    AllowRule(
        tool="file_edit",
        matcher=lambda caller, p: caller == "keeper" and (
            str(p.get("path", "")).replace("\\", "/").endswith("app/config/settings.py") or
            str(p.get("path", "")).replace("\\", "/").endswith(".env")
        ),
        reason="keeper has edit authority over settings.py and .env",
    ),
    AllowRule(
        tool="file_write",
        matcher=lambda caller, p: caller == "keeper" and (
            str(p.get("path", "")).replace("\\", "/").endswith("app/config/settings.py") or
            str(p.get("path", "")).replace("\\", "/").endswith(".env")
        ),
        reason="keeper has write authority over settings.py and .env",
    ),
)


def hardcoded_check(
    tool: str, params: dict, caller: str = ""
) -> tuple[Literal["allow", "deny", "ambiguous"], str]:
    """Layer-1 classifier. Returns (decision, reason).

    - ``"allow"`` — tool not risky / no rule matched and tool is not in RISKY_TOOLS
       OR a caller-aware ALLOW rule fired (fast-path for blessed callers)
    - ``"deny"`` — a hardcoded rule fired; ``reason`` describes which
    - ``"ambiguous"`` — tool IS risky but no hardcoded rule fired; caller
       should escalate to the security agent LLM for further classification

    DENY rules are checked BEFORE ALLOW rules — defense in depth means the
    absolute protections (target=master/security, paths outside project_root,
    destructive shell patterns) win over caller authority.
    """
    if tool not in RISKY_TOOLS and tool not in _PATTERN_DENY_TOOLS:
        return "allow", ""

    # Pass 1: caller-aware ALLOW rules (fast-path for blessed callers).
    #
    # Checked BEFORE DENY so explicit authority overrides the broad
    # "critical config file" deny that would otherwise block keeper from
    # editing agent-settings.json (which is keeper's job).
    #
    # Defense in depth: each ALLOW matcher must check its own target
    # constraints (e.g. `kill_agent` allow requires target NOT in
    # {master, security}). Permissive ALLOW rules are a bug.
    if caller:
        for rule in HARDCODED_ALLOW:
            if rule.tool != tool:
                continue
            try:
                matched = rule.matcher(caller, params)
            except Exception:
                continue
            if matched:
                return "allow", rule.reason

    # Pass 2: DENY rules — applied to anyone the ALLOW rules didn't bless.
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
