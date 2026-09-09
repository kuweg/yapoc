"""Agent-facing git tools.

These run against a real temporary repository rather than a mocked subprocess:
the whole point of the tools is what git actually does with the arguments they
build, and a mock would only assert that the code calls itself as written.

The safety property under test throughout is *scoping*. This repo is routinely
worked on by a human and several agents at once, which is exactly why
``app/backend/git_safety.py`` refuses automatic commits — a dirty-file diff
cannot say who made it. These tools take the other route: they only ever touch
paths the caller named, so a concurrent editor's work cannot be swept into an
agent's commit or discarded by its rollback.
"""

from __future__ import annotations

import subprocess

import pytest

from app.utils.tools import SandboxPolicy
from app.utils.tools.git import (
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitRestoreTool,
    GitShowTool,
    GitStatusTool,
)


def _run(*args: str, cwd) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo at a temp path, wired in as ``settings.project_root``."""
    from app.config import settings

    _run("init", "-q", "-b", "main", cwd=tmp_path)
    _run("config", "user.email", "test@example.com", cwd=tmp_path)
    _run("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "tracked.py").write_text("original\n")
    (tmp_path / "other.py").write_text("other original\n")
    _run("add", "-A", cwd=tmp_path)
    _run("commit", "-qm", "initial", cwd=tmp_path)

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    return tmp_path


def _dirty(repo) -> set[str]:
    # Deliberately NOT via _run(): porcelain lines are "XY path" and the
    # unstaged column is a leading space, so .strip() would eat one character
    # off the first path. app/backend/git_safety.py carries the same warning.
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout
    return {line[3:].strip() for line in out.splitlines() if line.strip()}


# ── Inspection ────────────────────────────────────────────────────────────


async def test_status_reports_branch_and_clean_tree(repo):
    out = await GitStatusTool().execute()
    assert "On branch main" in out
    assert "clean" in out


async def test_status_separates_staged_unstaged_and_untracked(repo):
    (repo / "tracked.py").write_text("edited\n")
    (repo / "new.py").write_text("new\n")
    (repo / "other.py").write_text("staged edit\n")
    _run("add", "other.py", cwd=repo)

    out = await GitStatusTool().execute()

    assert "tracked.py" in out
    assert "Untracked" in out and "new.py" in out
    assert "Staged" in out and "other.py" in out


async def test_diff_defaults_to_a_summary_when_no_paths_given(repo):
    """A whole-tree patch can be tens of thousands of lines — cost matters."""
    (repo / "tracked.py").write_text("edited\n")

    out = await GitDiffTool().execute()

    assert "tracked.py" in out
    assert "summary only" in out
    assert "+edited" not in out, "expected --stat, got the full patch"


async def test_diff_returns_the_patch_when_paths_are_named(repo):
    (repo / "tracked.py").write_text("edited\n")

    out = await GitDiffTool().execute(paths=["tracked.py"])

    assert "+edited" in out
    assert "-original" in out


async def test_diff_confirms_an_edit_landed(repo):
    """The file_edit silent-drop case: verify the write instead of trusting it."""
    assert "No changes" in await GitDiffTool().execute(paths=["tracked.py"])
    (repo / "tracked.py").write_text("actually written\n")
    assert "+actually written" in await GitDiffTool().execute(paths=["tracked.py"])


async def test_log_and_show_read_history(repo):
    log = await GitLogTool().execute()
    assert "initial" in log

    sha = _run("rev-parse", "HEAD", cwd=repo)
    shown = await GitShowTool().execute(ref=sha)
    assert "initial" in shown
    assert "tracked.py" in shown


async def test_unknown_ref_is_rejected(repo):
    out = await GitShowTool().execute(ref="no-such-ref")
    assert out.startswith("ERROR:")
    assert "unknown ref" in out


# ── Commit scoping — the core safety property ─────────────────────────────


async def test_commit_stages_only_the_named_paths(repo):
    """A concurrent editor's dirty file must survive an agent's commit."""
    (repo / "tracked.py").write_text("agent edit\n")
    (repo / "other.py").write_text("human edit, uncommitted\n")

    out = await GitCommitTool().execute(paths=["tracked.py"], message="agent change")

    assert "Committed" in out
    # The human's file is still dirty — it was not swept in.
    assert _dirty(repo) == {"other.py"}
    assert "agent change" in _run("log", "-1", "--pretty=%s", cwd=repo)


async def test_commit_leaves_someone_elses_staged_work_in_the_index(repo):
    """`--only` re-scopes the commit; a racing `git add` must not ride along."""
    (repo / "tracked.py").write_text("agent edit\n")
    (repo / "other.py").write_text("human edit\n")
    _run("add", "other.py", cwd=repo)  # human staged theirs first

    await GitCommitTool().execute(paths=["tracked.py"], message="agent change")

    committed = _run("show", "--name-only", "--pretty=format:", "HEAD", cwd=repo)
    assert "tracked.py" in committed
    assert "other.py" not in committed, "another writer's staged file was committed"


async def test_commit_requires_explicit_paths(repo):
    (repo / "tracked.py").write_text("edited\n")

    out = await GitCommitTool().execute(paths=[], message="sweep everything")

    assert out.startswith("ERROR:")
    assert "never stages or restores by wildcard" in out
    assert _dirty(repo) == {"tracked.py"}, "nothing should have been committed"


async def test_commit_requires_a_message(repo):
    (repo / "tracked.py").write_text("edited\n")
    out = await GitCommitTool().execute(paths=["tracked.py"], message="  ")
    assert out.startswith("ERROR:")


async def test_commit_with_nothing_to_commit_says_so(repo):
    out = await GitCommitTool().execute(paths=["tracked.py"], message="no-op")
    assert "Nothing to commit" in out


# ── Restore ───────────────────────────────────────────────────────────────


async def test_restore_undoes_a_bad_edit(repo):
    (repo / "tracked.py").write_text("broken\n")

    out = await GitRestoreTool().execute(paths=["tracked.py"])

    assert "Restored" in out
    assert (repo / "tracked.py").read_text() == "original\n"


async def test_restore_touches_only_the_named_paths(repo):
    (repo / "tracked.py").write_text("agent broke this\n")
    (repo / "other.py").write_text("human work in progress\n")

    await GitRestoreTool().execute(paths=["tracked.py"])

    assert (repo / "tracked.py").read_text() == "original\n"
    assert (repo / "other.py").read_text() == "human work in progress\n"


async def test_restore_requires_explicit_paths(repo):
    (repo / "tracked.py").write_text("edited\n")
    out = await GitRestoreTool().execute(paths=[])
    assert out.startswith("ERROR:")
    assert (repo / "tracked.py").read_text() == "edited\n"


# ── Path validation ───────────────────────────────────────────────────────


async def test_paths_escaping_the_project_root_are_rejected(repo):
    out = await GitCommitTool().execute(paths=["../outside.py"], message="escape")
    assert out.startswith("ERROR:")
    assert "escapes the project root" in out


async def test_option_like_paths_are_rejected(repo):
    """Otherwise a `path` becomes a git flag — arbitrary-execution territory."""
    for bad in ("--upload-pack=touch /tmp/pwned", "-c", "--exec-path=/tmp"):
        out = await GitCommitTool().execute(paths=[bad], message="m")
        assert out.startswith("ERROR:"), f"{bad!r} was not rejected"
        assert "command-line option" in out


async def test_option_like_refs_are_rejected(repo):
    out = await GitDiffTool().execute(ref="--output=/tmp/pwned")
    assert out.startswith("ERROR:")
    assert "command-line option" in out


async def test_option_like_branch_names_are_rejected(repo):
    out = await GitBranchTool().execute(action="create", name="--help")
    assert out.startswith("ERROR:")


# ── Sandbox ───────────────────────────────────────────────────────────────


async def test_sandbox_forbidden_paths_block_a_commit(repo):
    sandbox = SandboxPolicy(forbidden_paths=["app/agents/master/"])
    (repo / "app" / "agents" / "master").mkdir(parents=True)
    (repo / "app" / "agents" / "master" / "PROMPT.MD").write_text("x\n")

    out = await GitCommitTool(sandbox=sandbox).execute(
        paths=["app/agents/master/PROMPT.MD"], message="reach around file_write"
    )

    assert out.startswith("ERROR:")
    assert "forbidden_paths" in out


async def test_sandbox_forbidden_paths_block_a_restore(repo):
    """Restore overwrites a file as surely as a write — same lock applies."""
    sandbox = SandboxPolicy(forbidden_paths=["app/agents/master/"])

    out = await GitRestoreTool(sandbox=sandbox).execute(
        paths=["app/agents/master/PROMPT.MD"]
    )

    assert out.startswith("ERROR:")
    assert "forbidden_paths" in out


# ── Branches ──────────────────────────────────────────────────────────────


async def test_branch_create_and_switch(repo):
    assert "Created and switched" in await GitBranchTool().execute(
        action="create_and_switch", name="task/demo"
    )
    assert _run("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "task/demo"
    assert "task/demo" in await GitBranchTool().execute(action="list")


async def test_branch_rejects_an_invalid_name(repo):
    out = await GitBranchTool().execute(action="create", name="bad..name")
    assert out.startswith("ERROR:")


# ── Not a repo ────────────────────────────────────────────────────────────


async def test_tools_degrade_cleanly_outside_a_repository(tmp_path, monkeypatch):
    from app.config import settings

    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    monkeypatch.setattr(type(settings), "project_root", property(lambda self: plain))

    for tool in (GitStatusTool(), GitDiffTool(), GitLogTool()):
        out = await tool.execute()
        assert "not a git repository" in out
