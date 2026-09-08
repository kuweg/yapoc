"""Phase 2.6 — adversarial regression suite for the Layer-1 security gate.

`app/utils/tools/security_policy.py` is ~400 lines of substring and regex
heuristics guarding destructive operations, and it had zero tests. Writing
these found four working bypasses, all now fixed and pinned below:

1. `app/agents/planning/../security/PROMPT.MD` — traversal past the lock on the
   security agent's own directory, the lock whose entire purpose is to stop the
   gate being rewritten from inside the system.
2. `app//agents//security//PROMPT.MD` — same lock, duplicate separators.
3. `rm -fr /`, `rm -r -f /`, `rm --recursive --force /` — the destructive-shell
   rule only matched the literal spelling `rm -rf`.
4. `sh -c 'rm -rf /'` — quoted, so `/` is followed by `'` and both the `\\s|$`
   and `/[a-zA-Z]` anchors missed.

The suite is written attack-first: each test states the operation an attacker
(or a confused agent) would attempt, and asserts the gate refuses it.
"""

from __future__ import annotations

import pytest

from app.utils.tools.security_policy import (
    RISKY_TOOLS,
    HARDCODED_ALLOW,
    _rm_hits_root,
    _normalize_path,
    _under_security_dir,
    _has_critical_suffix,
    hardcoded_check,
)


def deny(tool, params, caller=""):
    decision, reason = hardcoded_check(tool, params, caller)
    return decision == "deny", reason


# ── Path traversal into the security agent's directory ─────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "app/agents/security/PROMPT.MD",
        "./app/agents/security/PROMPT.MD",
        "app/agents/planning/../security/PROMPT.MD",
        "app//agents//security//PROMPT.MD",
        "app/agents/security/../security/./PROMPT.MD",
        "app/agents/./security/PROMPT.MD",
        "app/agents/security/CONFIG.yaml",
        "/abs/path/app/agents/security/PROMPT.MD",
    ],
)
@pytest.mark.parametrize("tool", ["file_write", "file_edit"])
def test_security_directory_is_write_locked(tool, path):
    """No spelling of the security dir may be written — that lock is what stops
    the gate being silently rewritten from inside the system."""
    blocked, reason = deny(tool, {"path": path}, "builder")
    assert blocked, f"{tool} {path!r} was NOT denied"
    assert "security" in reason


def test_normalize_path_collapses_traversal_and_separators():
    assert _normalize_path("app/agents/planning/../security/PROMPT.MD") == (
        "app/agents/security/PROMPT.MD"
    )
    assert _normalize_path("app//agents//security//PROMPT.MD") == (
        "app/agents/security/PROMPT.MD"
    )
    assert _normalize_path("./.env") == ".env"
    assert _normalize_path("") == ""
    assert _under_security_dir("app/agents/planning/../security/x")
    assert not _under_security_dir("app/agents/planning/PROMPT.MD")


# ── Critical config file deletion ──────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "./.env",
        "app/../.env",
        "app/config/settings.py",
        "./app/config/settings.py",
        "app/config/../config/settings.py",
        "app/config/agent-settings.json",
        "app/agents/master/PROMPT.MD",
        "app/agents/security/PROMPT.MD",
    ],
)
def test_critical_files_cannot_be_deleted(path):
    """Deletion is the irrecoverable failure mode; edits are git-revertible."""
    blocked, _ = deny("file_delete", {"path": path}, "builder")
    assert blocked, f"deletion of {path!r} was NOT denied"


def test_dotenv_prefix_stripping_does_not_eat_the_leading_dot():
    """A naive lstrip('./') turns '.env' into 'env' and silently unprotects it."""
    assert _has_critical_suffix("./.env")
    assert _has_critical_suffix(".env")


def test_editing_critical_config_is_allowed_by_design():
    """Documented policy: edits are reversible and keeper needs them."""
    for tool in ("file_write", "file_edit"):
        blocked, _ = deny(tool, {"path": "app/config/agent-settings.json"}, "keeper")
        assert not blocked


# ── Destructive shell commands ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf  /",
        "rm -fr /",
        "rm -r -f /",
        "rm -Rf /",
        "rm --recursive --force /",
        "rm --force --recursive /",
        "sh -c 'rm -rf /'",
        'bash -c "rm -rf /"',
        "/bin/rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        "rm -rf ${HOME}",
        "rm -rf /etc",
        "rm -rf /usr/lib",
        "cd /tmp && rm -rf /",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        ":(){ :|:& };:",
        "shutdown -h now",
        "reboot",
    ],
)
def test_destructive_shell_commands_are_denied(command):
    """Denied for EVERY caller, including the shell-blessed builder/master."""
    for caller in ("builder", "master", "planning", ""):
        blocked, _ = deny("shell_exec", {"command": command}, caller)
        assert blocked, f"{command!r} was NOT denied for caller={caller!r}"


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git commit -m 'rm -rf a joke in a message'",
        "ls -la app/agents",
        "rm app/tmp/scratch.txt",
        "rm -rf app/frontend/dist",
        "rm -rf ./build",
        "curl -s -o /dev/null http://localhost:8000/api/health",
        "echo hello > /dev/null",
        "cd app/frontend && pnpm run build",
        "poetry run pytest tests/ -q",
    ],
)
def test_legitimate_shell_commands_are_not_denied(command):
    """False positives block real work — the suite must pin both directions."""
    blocked, reason = deny("shell_exec", {"command": command}, "builder")
    assert not blocked, f"{command!r} was wrongly denied: {reason}"


def test_rm_hits_root_is_flag_order_and_quote_independent():
    assert _rm_hits_root("rm -fr /")
    assert _rm_hits_root("rm -r -f /")
    assert _rm_hits_root("sh -c 'rm -rf /'")
    assert _rm_hits_root("rm --recursive /")
    assert not _rm_hits_root("rm -rf app/build")
    assert not _rm_hits_root("echo 'this mentions rm but runs nothing'")


# ── Core-agent protection, including for blessed callers ───────────────────


@pytest.mark.parametrize("target", ["master", "security"])
def test_core_agents_cannot_be_killed_even_by_master(target):
    """master holds kill authority; that authority must not reach itself."""
    blocked, _ = deny("kill_agent", {"agent_name": target}, "master")
    assert blocked, f"kill of {target} by master was NOT denied"


@pytest.mark.parametrize(
    "target",
    ["master", "planning", "builder", "keeper", "doctor",
     "model_manager", "security", "evaluator"],
)
def test_core_agents_cannot_be_deleted_even_by_master(target):
    blocked, _ = deny("delete_agent", {"name": target}, "master")
    assert blocked, f"delete of core agent {target} was NOT denied"


@pytest.mark.parametrize("target", ["master", "security"])
def test_core_agent_config_and_memory_are_protected_from_keeper(target):
    """keeper holds config authority; it must not reach master/security."""
    blocked, _ = deny("update_agent_config", {"name": target}, "keeper")
    assert blocked
    blocked, _ = deny("agent_amnesia", {"name": target}, "master")
    assert blocked


def test_blessed_callers_still_lose_to_absolute_protections():
    """The allow-first ordering is only safe while matchers self-check."""
    assert deny("kill_agent", {"agent_name": "master"}, "master")[0]
    assert deny("shell_exec", {"command": "rm -rf /"}, "builder")[0]
    assert deny("shell_exec", {"command": "rm -rf /"}, "master")[0]


def test_every_allow_rule_is_caller_scoped():
    """An ALLOW rule that ignores its caller would bless the whole system.

    Allow is checked before deny, so a matcher that returns True for any caller
    is a gate bypass rather than a convenience.
    """
    offenders = []
    for rule in HARDCODED_ALLOW:
        # A rule must not fire for an unknown caller on an empty payload.
        try:
            if rule.matcher("some-random-agent", {}):
                offenders.append(rule.tool)
        except Exception:
            pass
    assert not offenders, f"caller-agnostic ALLOW rules: {offenders}"


# ── Escalation contract ────────────────────────────────────────────────────


def test_risky_tool_without_a_matching_rule_escalates():
    """Unmatched risky calls must reach the LLM layer, never silently pass."""
    decision, _ = hardcoded_check("file_delete", {"path": "app/tmp/x.txt"}, "planning")
    assert decision == "ambiguous"


def test_non_risky_tools_are_free():
    for tool in ("file_read", "web_search", "memory_append", "notes_read"):
        assert hardcoded_check(tool, {}, "builder")[0] == "allow"


def test_risky_tool_set_is_not_silently_shrunk():
    """Removing a tool from RISKY_TOOLS disables its gate entirely."""
    assert {
        "file_delete", "shell_exec", "delete_agent", "update_agent_config",
        "agent_amnesia", "kill_agent", "update_config",
    } <= RISKY_TOOLS


def test_malformed_params_do_not_crash_or_allow():
    """A broken payload must not become an accidental allow for a risky tool."""
    for params in ({}, {"path": None}, {"command": None}, {"name": 12345}):
        decision, _ = hardcoded_check("shell_exec", params, "builder")
        assert decision in {"deny", "ambiguous", "allow"}
        decision, _ = hardcoded_check("delete_agent", params, "planning")
        assert decision in {"deny", "ambiguous"}


# ── Audit completeness (Phase 2.6) ─────────────────────────────────────────
#
# Every decision the gate makes must leave a forensic record. A silent allow is
# indistinguishable from "the gate never ran", which is precisely the state you
# cannot afford to be unsure about after an incident.


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """Redirect AUDIT.MD to a temp file and return a reader for it."""
    from app.utils.tools import security_gate as gate

    path = tmp_path / "AUDIT.MD"
    monkeypatch.setattr(gate, "_AUDIT_PATH", path)
    gate.cache_clear()

    def read():
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    return read


async def test_hardcoded_deny_is_audited(audit_log):
    from app.utils.tools import security_gate as gate

    decision, _ = await gate.classify("shell_exec", {"command": "rm -rf /"}, "builder")
    assert decision == "deny"
    lines = audit_log()
    assert len(lines) == 1
    assert "decision=deny" in lines[0]
    assert "source=hardcoded" in lines[0]
    assert "caller=builder" in lines[0]


async def test_hardcoded_allow_is_audited(audit_log):
    from app.utils.tools import security_gate as gate

    decision, _ = await gate.classify("file_read", {"path": "README.md"}, "builder")
    assert decision == "allow"
    lines = audit_log()
    assert len(lines) == 1 and "decision=allow" in lines[0]


async def test_security_agent_bypass_is_audited(audit_log):
    """The recursion-guard bypass is the most important line to record."""
    from app.utils.tools import security_gate as gate

    decision, _ = await gate.classify("shell_exec", {"command": "rm -rf /"}, "security")
    assert decision == "allow"
    lines = audit_log()
    assert len(lines) == 1
    assert "source=bypass" in lines[0]
    assert "caller=security" in lines[0]


async def test_llm_escalation_is_audited(audit_log, monkeypatch):
    from app.utils.tools import security_gate as gate

    async def _fake_llm(tool, params, caller):
        return "deny", "llm says no"

    monkeypatch.setattr(gate, "_classify_via_llm", _fake_llm)

    decision, reason = await gate.classify(
        "file_delete", {"path": "app/tmp/x.txt"}, "planning"
    )
    assert decision == "deny"
    lines = audit_log()
    assert len(lines) == 1
    assert "source=llm" in lines[0]
    assert "llm says no" in lines[0]


async def test_cached_llm_decisions_are_still_audited(audit_log, monkeypatch):
    """A cache hit must not skip the audit — otherwise repeat attempts vanish."""
    from app.utils.tools import security_gate as gate

    calls = []

    async def _fake_llm(tool, params, caller):
        calls.append(1)
        return "deny", "llm says no"

    monkeypatch.setattr(gate, "_classify_via_llm", _fake_llm)

    params = {"path": "app/tmp/y.txt"}
    await gate.classify("file_delete", params, "planning")
    await gate.classify("file_delete", params, "planning")

    assert len(calls) == 1, "second call should have hit the cache"
    assert len(audit_log()) == 2, "cached decision was not audited"


async def test_audit_failure_never_blocks_a_decision(tmp_path, monkeypatch):
    """Forensics must not become an availability risk."""
    from app.utils.tools import security_gate as gate

    unwritable = tmp_path / "nope" / "AUDIT.MD"
    monkeypatch.setattr(gate, "_AUDIT_PATH", unwritable)
    monkeypatch.setattr(
        type(unwritable.parent),
        "mkdir",
        lambda self, *a, **k: (_ for _ in ()).throw(OSError("read-only fs")),
    )
    gate.cache_clear()

    decision, _ = await gate.classify("shell_exec", {"command": "rm -rf /"}, "builder")
    assert decision == "deny", "a failing audit write must not change the verdict"


# ── Outward-facing tools (plugin system) ───────────────────────────────────
#
# The Gmail/Calendar plugins introduced the first tools that act on the OUTSIDE
# WORLD as the user. Everything the gate guarded before could only damage YAPOC
# or the host, and that damage is recoverable — git checkpoints, rollback, a
# rebuilt agent. An email cannot be unsent.
#
# When these landed, all 14 agents held `plugin:gmail:*` (including cron,
# doctor and librarian, which run autonomously) and `gmail_send` was ungated:
# no review, no audit record.


def _patch_failing_provider(monkeypatch):
    """Make the provider call inside `_classify_via_llm` raise.

    Patching `_classify_via_llm` wholesale would replace the try/except being
    tested, so the failure is injected one level down at the adapter.
    """
    from app.agents.security import security_agent

    class _DeadAdapter:
        async def complete(self, **kwargs):
            raise RuntimeError("provider down")

    async def _cfg():
        return None

    async def _adapter(_cfg_arg):
        return _DeadAdapter()

    async def _prompt(_name):
        return "You are the security gate."

    monkeypatch.setattr(security_agent, "_load_config", _cfg)
    monkeypatch.setattr(security_agent, "_load_adapter", _adapter)
    monkeypatch.setattr(security_agent, "_read_file", _prompt)



@pytest.mark.parametrize(
    "tool",
    ["gmail_send", "mail_send", "calendar_create_event",
     "plugin:gmail:send", "plugin:mail:send", "plugin:calendar:create_event"],
)
def test_outward_facing_tools_are_gated(tool):
    """Both spellings must be gated — the loader registers each tool twice."""
    from app.utils.tools.security_policy import is_outward_facing

    assert is_outward_facing(tool)
    decision, _ = hardcoded_check(tool, {"to": "someone@example.com"}, "builder")
    assert decision == "ambiguous", (
        f"{tool} bypassed the gate — an agent could send as the user unreviewed"
    )


@pytest.mark.parametrize(
    "tool",
    ["gmail_read", "gmail_list", "gmail_search", "calendar_list_events",
     "plugin:gmail:list", "plugin:calendar:list_events"],
)
def test_read_only_plugin_tools_stay_free(tool):
    """Gating reads too would make the integration useless for no safety gain."""
    from app.utils.tools.security_policy import is_outward_facing

    assert not is_outward_facing(tool)
    assert hardcoded_check(tool, {}, "builder")[0] == "allow"


def test_namespaced_alias_cannot_bypass_the_gate():
    """Gating one spelling while the loader registers two is a free bypass."""
    plain, _ = hardcoded_check("gmail_send", {}, "builder")
    namespaced, _ = hardcoded_check("plugin:gmail:send", {}, "builder")
    assert plain == namespaced == "ambiguous"


async def test_outward_facing_tools_fail_closed_when_review_is_unavailable(audit_log, monkeypatch):
    """"The reviewer was down" is not a reason to send mail as the user.

    Recoverable tools deliberately fail open — blocking everything on a provider
    hiccup would halt the system, and that damage is undoable. An email is not.
    """
    from app.utils.tools import security_gate as gate

    _patch_failing_provider(monkeypatch)

    decision, reason = await gate.classify(
        "gmail_send", {"to": "stranger@example.com"}, "cron"
    )
    assert decision == "deny", "outward-facing tool was allowed with no review"
    assert "outward-facing" in reason
    assert any("decision=deny" in line for line in audit_log())


async def test_recoverable_tools_still_fail_open(audit_log, monkeypatch):
    """The existing tradeoff must survive: don't halt the system on a hiccup."""
    from app.utils.tools import security_gate as gate

    _patch_failing_provider(monkeypatch)

    decision, _ = await gate.classify("file_delete", {"path": "app/tmp/x"}, "builder")
    assert decision == "allow"


async def test_sending_mail_is_audited(audit_log, monkeypatch):
    """Every send must leave a forensic record naming the caller."""
    from app.utils.tools import security_gate as gate

    async def _approve(tool, params, caller):
        return "allow", "reviewed"

    monkeypatch.setattr(gate, "_classify_via_llm", _approve)  # noqa: E501

    await gate.classify("gmail_send", {"to": "x@example.com"}, "cron")
    lines = audit_log()
    assert len(lines) == 1
    assert "gmail_send" in lines[0]
    assert "caller=cron" in lines[0]
