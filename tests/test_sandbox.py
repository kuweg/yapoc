"""Tests for sandbox enforcement — SandboxPolicy and _sandbox path validation."""

import pytest
from pathlib import Path

from app.utils.tools import SandboxPolicy


def test_sandbox_policy_defaults():
    policy = SandboxPolicy()
    assert policy.forbidden_paths == []
    assert policy.shell_allowlist == []


def test_is_forbidden_blocks_forbidden_paths():
    policy = SandboxPolicy(forbidden_paths=["app/agents", "app/backend"])
    assert policy.is_forbidden("app/agents/master/PROMPT.MD") is True
    assert policy.is_forbidden("app/backend/main.py") is True
    assert policy.is_forbidden("app/utils/db.py") is False
    assert policy.is_forbidden("projects/test.py") is False


def test_is_forbidden_empty_means_nothing_forbidden():
    policy = SandboxPolicy(forbidden_paths=[])
    assert policy.is_forbidden("anything/goes.py") is False


def test_shell_allowlist_permits_listed_commands():
    policy = SandboxPolicy(shell_allowlist=["poetry", "git"])
    assert policy.is_shell_allowed("poetry install") is True
    assert policy.is_shell_allowed("poetry add numpy") is True
    assert policy.is_shell_allowed("git status") is True
    assert policy.is_shell_allowed("rm -rf /") is False
    assert policy.is_shell_allowed("pip install foo") is False


def test_shell_allowlist_empty_means_all_allowed():
    policy = SandboxPolicy(shell_allowlist=[])
    assert policy.is_shell_allowed("rm -rf /") is True
    assert policy.is_shell_allowed("anything") is True


def test_parse_sandbox_policy_from_config():
    from app.utils.tools import _parse_sandbox_policy
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "CONFIG.md"
        config_path.write_text("""adapter: anthropic
model: test
tools:
  - file_read
sandbox:
  forbidden:
    - app/agents
    - app/backend
  shell_allowlist:
    - poetry
    - git
runner:
  max_turns: 10
""")
        policy = _parse_sandbox_policy(Path(tmpdir))
        assert "app/agents" in policy.forbidden_paths
        assert "app/backend" in policy.forbidden_paths
        assert "poetry" in policy.shell_allowlist
        assert "git" in policy.shell_allowlist


def test_parse_sandbox_policy_missing_config():
    from app.utils.tools import _parse_sandbox_policy
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # No CONFIG.md
        policy = _parse_sandbox_policy(Path(tmpdir))
        assert policy.forbidden_paths == []
        assert policy.shell_allowlist == []
