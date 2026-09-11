"""Hardcoded security deny rules — the fast path for the security gate.

Layer 1 of the security gate. Pure synchronous classifier, no LLM call:
- Absolute self-destruction (kill/delete/amnesia of master+security; writes
  under app/agents/security/; deletion of critical config files)
- Absolute system-destruction (rm -rf /, dd if=, paths outside project_root)

Edits (not deletions) to critical config files like settings.py, .env, and
agent-settings.json are intentionally NOT hardcode-denied — agents (notably
keeper, master) need to edit them for routine ops, and edits are reversible
via git. Deletion of those files IS still denied; that's the actual
irrecoverable failure mode.

Anything that's RISKY but doesn't match a hardcoded rule falls through as
``"ambiguous"`` and the caller (security_gate.classify) escalates to the
security agent LLM for classification.

Rules are deliberately conservative — false positives hurt less than false
negatives. Each rule documents its rationale via the `reason` field which
is surfaced to the caller and persisted to AUDIT.MD.
"""
from __future__ import annotations

import os
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
    "execute_code",
    "delete_agent",
    "update_agent_config",
    "agent_amnesia",
    "kill_agent",
    "update_config",
    # git_restore overwrites working-tree files from a commit, destroying
    # uncommitted work in the paths it names. The other git tools are either
    # read-only (status/diff/log/show) or additive and reversible
    # (commit/branch), so they are not gated.
    "git_restore",
})

# Tools that act on the OUTSIDE WORLD as the user: sending mail, creating
# calendar entries. Categorically different from everything above, which can
# only damage YAPOC or the host — that damage is recoverable (git checkpoints,
# rollback, a rebuilt agent). An email cannot be unsent, and it goes out under
# the user's own identity.
#
# Every agent currently holds `plugin:gmail:*`, including the ones that run
# autonomously on a schedule (cron, doctor, librarian). Combined with the
# researcher's web tools, untrusted fetched content reaching an agent that can
# both read the user's mail and send mail is the classic exfiltration chain, so
# these are gated rather than free.
#
# Matched by suffix as well as exact name because the plugin loader registers
# each tool twice: `gmail_send` and the namespaced `plugin:gmail:send`. Gating
# only one spelling would leave the other as a trivial bypass.
_OUTWARD_ACTION_SUFFIXES: tuple[str, ...] = (
    "gmail_send", "mail_send", "calendar_create_event",
    "github_create_draft_pull_request", "github_update_draft_pull_request",
    ":github:create_draft_pull_request", ":github:update_draft_pull_request",
    "github_create_issue", "github_comment_on_issue", "github_comment_on_pull_request", "github_update_labels",
    ":github:create_issue", ":github:comment_on_issue", ":github:comment_on_pull_request", ":github:update_labels",
    ":gmail:send", ":mail:send", ":calendar:create_event",
)


def is_outward_facing(tool: str) -> bool:
    """True for tools that take an irreversible action in the outside world."""
    name = (tool or "").strip()
    return any(name == s or name.endswith(s) for s in _OUTWARD_ACTION_SUFFIXES)

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


def _normalize_path(raw: str) -> str:
    """Collapse a path to its canonical textual form before rule matching.

    Rules below match on path SUBSTRINGS, which is only sound if the path is
    normalized first. Two forms slipped past the security-directory lock:

        app/agents/planning/../security/PROMPT.MD
        app//agents//security//PROMPT.MD

    Both resolve to the same real file as `app/agents/security/PROMPT.MD`, but
    neither contains the literal substring `/agents/security/`, so the write
    lock on the security agent's own directory — the lock that stops the gate
    being rewritten from inside the system — did not fire.

    `os.path.normpath` collapses `..` segments and duplicate separators
    textually, without touching the filesystem, so it works on paths that do
    not exist yet (a write target usually does not).
    """
    n = raw.replace("\\", "/").strip()
    if not n:
        return ""
    # normpath on "" returns ".", and it strips a trailing slash we do not need.
    normalized = os.path.normpath(n).replace("\\", "/")
    # normpath keeps a leading "./" off, but preserve a leading "/" for
    # absolute paths so the absolute-form checks below still work.
    return normalized


def _has_critical_suffix(raw: str) -> bool:
    # `lstrip("./")` would also strip the leading `.` of `.env`, turning it
    # into `env` and silently bypassing the rule. normpath handles the `./`
    # prefix (and `..` segments) without that hazard.
    n = _normalize_path(raw)
    return any(n.endswith(suf) for suf in _CRITICAL_PATH_SUFFIXES)


def _as_path_list(raw: object) -> list[str]:
    """Coerce a tool's ``paths`` param into a list of strings.

    The git tools take a list where the file tools take a single ``path``.
    A matcher that assumed one shape would silently never fire on the other,
    which in a deny rule reads as "allowed".
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [str(raw)]


def _under_security_dir(raw: str) -> bool:
    norm = _normalize_path(raw)
    return (
        "/agents/security/" in norm
        or norm.startswith("agents/security/")
        or "app/agents/security/" in norm
    )


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
    from . import shell_arguments
    from .poetry_execution import operation, safe_inspection
    try:
        argv = shell_arguments(command)
        if operation(argv) in {'read', 'dependencies'} or safe_inspection(argv):
            return False
    except ValueError:
        pass
    for match in _ABS_PATH_TOKEN_RE.finditer(command):
        token = match.group(0)
        if any(token == p or token.startswith(p + "/") for p in _SAFE_ABS_PATH_PREFIXES):
            continue
        if not _path_in_project(token):
            return True
    return False


# Targets that make an `rm` catastrophic regardless of flag spelling.
_RM_ROOT_TARGETS: frozenset[str] = frozenset({
    "/", "/*", "/.", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "$HOME/*",
})


def _rm_hits_root(command: str) -> bool:
    r"""True if ``command`` runs `rm` recursively against root or $HOME.

    The regex list below only ever matched the exact spelling `rm -rf <target>`,
    which four working variants walked straight past:

        rm -fr /                  flags in the other order
        rm -r -f /                flags split into separate tokens
        rm --recursive --force /  long flags
        sh -c 'rm -rf /'          quoted — the `/` is followed by `'`, so the
                                  `\s|$` and `/[a-zA-Z]` anchors both missed

    Rather than add four more regexes (and miss the fifth), this tokenizes:
    quotes become separators, then for each `rm` token the following flag
    tokens are collected and the first non-flag token is the target. That makes
    the check independent of flag order, spelling and quoting.

    Kept deliberately conservative per this module's stated posture — a false
    positive costs one blocked command, a false negative costs the machine.
    """
    # Quotes only group tokens for the shell; for our purposes they are
    # separators, which is what makes `sh -c 'rm -rf /'` visible.
    tokens = [t for t in re.split(r"[\s'\"]+", command) if t]
    for i, token in enumerate(tokens):
        # Match the command itself, not a substring of another word, and not a
        # path like /usr/bin/rm's basename appearing mid-argument.
        if token != "rm" and not token.endswith("/rm"):
            continue
        recursive = False
        for candidate in tokens[i + 1:]:
            if candidate.startswith("--"):
                if candidate in {"--recursive", "--force"}:
                    recursive = recursive or candidate == "--recursive"
                    continue
                continue
            if candidate.startswith("-"):
                # Short bundle: -rf, -fr, -Rf, -r ...
                if any(c in "rR" for c in candidate[1:]):
                    recursive = True
                continue
            # First non-flag token is the target.
            if candidate in _RM_ROOT_TARGETS:
                return True
            # A root-level absolute path (/etc, /usr, ...). Parity with the
            # original `rm -rf /[a-zA-Z]` rule, which blocked these outright.
            if recursive and re.match(r"^/[a-zA-Z]", candidate):
                return True
            break
    return False


def _shell_is_destructive(command: str) -> bool:
    """True if ``command`` matches any hardcoded system-destruction pattern."""
    if _rm_hits_root(command):
        return True
    return any(pat.search(command) for pat in _SHELL_DESTRUCTION_PATTERNS)


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
    # The security agent's own directory stays write-locked — if anyone
    # could edit security/PROMPT.MD, the gate could be silently rewritten
    # from inside the system. This is the only path-based write block left.
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
    # Restoring security/PROMPT.MD from an older commit rewrites the gate just
    # as effectively as editing it — and would slip past the two rules above,
    # which only know about file_write/file_edit. Same lock, different verb.
    Rule(
        tool="git_restore",
        matcher=lambda p: any(
            _under_security_dir(str(item)) for item in _as_path_list(p.get("paths"))
        ),
        reason="restore of security agent file from git",
        category="self_destruction",
    ),
    # NOTE: critical config files (settings.py, .env, agent-settings.json,
    # master/PROMPT.MD) are intentionally NOT write-blocked here. The
    # `file_delete` rule above prevents their deletion, which is the actual
    # irrecoverable failure mode. Edits are reversible (git diff/revert),
    # and keeper/master need to edit them for routine ops — blocking those
    # forced keeper into write-scripts-then-shell-exec workarounds.
    # system-destruction: shell command patterns
    Rule(
        tool="shell_exec",
        matcher=lambda p: _shell_is_destructive(str(p.get("command", ""))),
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
# ORDER: ALLOW is checked BEFORE DENY (in hardcoded_check). The protection
# against blessed callers targeting master/security is enforced INSIDE each
# allow matcher (each one calls `_target_is_core_protected` or equivalent).
# This is allow-wins, with defense-in-depth baked into the matchers
# themselves rather than via ordering.

def _target_is_core_protected(params: dict) -> bool:
    """True if the param target is master or security — those stay protected
    even for blessed callers. Picked up by `kill_agent` / `update_agent_config`
    allow matchers as a safety conjunction."""
    target = str(params.get("name", "") or params.get("agent_name", ""))
    return target in {"master", "security"}


def _is_orphaned_agent_memory_file(raw: str) -> bool:
    """True if the path is a memory file inside app/agents/ that has been
    migrated to app/memory/agents/. Deleting these orphaned duplicates is
    safe — the live copy lives under app/memory/agents/."""
    norm = raw.replace("\\", "/")
    return (
        "app/agents/" in norm
        and "app/memory/agents/" not in norm
        and any(norm.endswith(f"/{f}") for f in ("MEMORY.MD", "NOTES.MD", "LEARNINGS.MD", "HEALTH.MD"))
    )


def _safe_poetry_shell(command: str) -> bool:
    from . import shell_arguments
    from .poetry_execution import operation, safe_inspection
    try:
        argv = shell_arguments(command)
        return operation(argv) in {'read', 'dependencies'} or safe_inspection(argv)
    except ValueError:
        return False


def _safe_frontend_shell(params: dict) -> bool:
    from . import project_shell_arguments
    from .javascript_execution import project_operation
    try:
        directory, argv = project_shell_arguments(str(params.get('command', '')))
        work = settings.project_root / str(params.get('cwd', '.'))
        if directory:
            work = work / directory
        if not work.resolve().is_relative_to(settings.project_root.resolve()):
            return False
        # Validate option paths and dependency paths, including ../ traversal.
        for arg in argv[1:]:
            value = arg.split('=', 1)[-1]
            if value.startswith(('~', '/')) or '..' in Path(value).parts:
                if not (work / value).resolve().is_relative_to(settings.project_root.resolve()):
                    return False
        return project_operation(argv)
    except (ValueError, OSError):
        return False


HARDCODED_ALLOW: tuple[AllowRule, ...] = (
    AllowRule(
        tool='shell_exec',
        matcher=lambda caller, p: caller in {'keeper', 'builder', 'master'} and _safe_frontend_shell(p),
        reason='project-local package installation or frontend build/test command',
    ),
    AllowRule(
        tool='shell_exec',
        matcher=lambda caller, p: caller in {'keeper', 'builder', 'master'} and _safe_poetry_shell(str(p.get('command', ''))),
        reason='validated project Poetry operation or managed-runtime inspection',
    ),
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
    # NOTE: file_edit / file_write on settings.py, .env, and agent-settings.json
    # no longer require an allow rule — the corresponding deny rules were
    # removed (deletion is what's protected, not edits). Anyone can edit
    # critical config files; deletion is still blocked by `file_delete` denies.
    # Master can delete orphaned memory files after migration to app/memory/agents/
    AllowRule(
        tool="file_delete",
        matcher=lambda caller, p: caller == "master" and _is_orphaned_agent_memory_file(str(p.get("path", ""))),
        reason="master can delete orphaned memory files after migration to app/memory/agents/",
    ),
    # Builder and master are the primary workers — they need git and general
    # shell commands as routine ops. Routing every `git status` / `curl`
    # through the Layer-2 LLM classifier was both too strict and flaky, so
    # we give them a fast-path allow — while baking the two hard safety nets
    # (destructive patterns + escaping project_root) into the matcher itself.
    # A destructive/escaping command fails the matcher and still falls through
    # to the HARDCODED_DENY rules below.
    AllowRule(
        tool="shell_exec",
        matcher=lambda caller, p: (
            caller in {"builder", "master"}
            and not _shell_is_destructive(str(p.get("command", "")))
            and not _shell_escapes_project(str(p.get("command", "")))
        ),
        reason="builder/master have shell authority within project_root",
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

    ORDER: ALLOW rules are checked BEFORE DENY rules. (This docstring
    previously claimed the opposite — deny-before-allow — while the code below
    has always done allow-first. In a security gate a stale ordering claim is
    worse than no comment, because a reader reasons about the wrong model.)

    Because allow wins, every ALLOW matcher is responsible for its own safety
    conjunctions: the `kill_agent` / `update_agent_config` matchers call
    `_target_is_core_protected`, and the `shell_exec` matcher re-checks both
    `_shell_is_destructive` and `_shell_escapes_project`. A permissive ALLOW
    rule is therefore a security bug, not merely a policy choice.
    """
    if (
        tool not in RISKY_TOOLS
        and tool not in _PATTERN_DENY_TOOLS
        and not is_outward_facing(tool)
    ):
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

    if tool in RISKY_TOOLS or is_outward_facing(tool):
        return "ambiguous", ""
    return "allow", ""
