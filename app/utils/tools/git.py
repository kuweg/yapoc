"""Agent-facing git tools — inspection, explicit-path commits, and rollback.

Why these exist
---------------
Agents mutate files and have no way to see, review, or undo the result. Two
concrete failures in this repo motivated the set:

* ``file_edit`` has been observed reporting success on edits that never
  persisted (builder burned ~30 turns / $1.77 on one). ``git_diff`` lets an
  agent *verify* its own change landed instead of trusting the write.
* Failed work is discarded whole. ``git_restore`` gives a scoped undo.

What is deliberately absent
---------------------------
``push``/``pull``/``fetch``/``remote`` — publishing to a remote is an
irreversible outside-world action taken under the user's identity, in the same
category as sending mail (see ``security_policy._OUTWARD_ACTION_SUFFIXES``).
Also absent: ``merge``, ``rebase``, ``reset``, ``cherry-pick``, ``stash``,
``clean``, ``tag`` — history rewriting and whole-tree destruction. An agent that
needs those should be asking a human.

There is no raw-argument passthrough anywhere in this module. Every parameter is
structured and validated. A tool that forwarded arbitrary git flags would hand
any agent holding it a shell (``git --exec-path``, ``--upload-pack``, ``-c
core.pager=``), bypassing both ``shell_exec``'s allowlist and the sandbox.

The shared-worktree rule
------------------------
``app/backend/git_safety.py`` refuses *automatic* commit and rollback because a
dirty-file diff cannot prove which writer produced it — a human editing
alongside an agent would have their work swept into the agent's commit. These
tools honour the same rule from the other direction: nothing here ever stages by
wildcard. ``git_commit`` and ``git_restore`` act on an explicit, non-empty path
list, so touching a file the caller did not name is structurally impossible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings

from . import BaseTool, SandboxPolicy


# Commands are run via exec (never a shell), so paths cannot glob or expand.
# The remaining injection surface is a path or ref being read as an option,
# which is why every invocation below puts `--` before its path list and why
# leading dashes are rejected outright.
_MAX_PATHS = 200


async def _git(*args: str, timeout: float = 20.0) -> tuple[int, str, str]:
    """Run git against the project root. Lazy import mirrors delegation.py."""
    from app.backend.git_safety import run_git

    return await run_git(*args, check=False, timeout=timeout)


async def _is_repo() -> bool:
    rc, out, _ = await _git("rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def _reject_option_like(value: str, label: str) -> str | None:
    """Refuse a value that git would parse as an option rather than data."""
    if value.startswith("-"):
        return f"ERROR: {label} '{value}' looks like a command-line option; refused."
    return None


def _normalize_paths(
    raw: Any, sandbox: SandboxPolicy | None, *, require: bool
) -> tuple[list[str], str | None]:
    """Validate a caller-supplied path list into project-relative git paths.

    Returns ``(paths, error)``. Enforces, in order: presence (when required),
    a sane count, no option-like entries, containment inside the project root,
    and the agent's sandbox ``forbidden_paths``.

    The sandbox check is the important one — an agent barred from *writing*
    ``app/agents/master/`` must not be able to reach the same file through
    ``git_restore``, which overwrites it just as effectively.
    """
    if raw is None:
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return [], "ERROR: 'paths' must be a list of strings."

    items = [str(p).strip() for p in raw if str(p).strip()]
    if require and not items:
        return [], (
            "ERROR: 'paths' is required and must name at least one file. "
            "This tool never stages or restores by wildcard — name the files "
            "you changed, so a concurrent editor's work is never swept in."
        )
    if len(items) > _MAX_PATHS:
        return [], f"ERROR: too many paths ({len(items)}); cap is {_MAX_PATHS}."

    root = settings.project_root.resolve()
    out: list[str] = []
    for item in items:
        if (err := _reject_option_like(item, "path")) is not None:
            return [], err
        candidate = Path(item)
        absolute = candidate if candidate.is_absolute() else root / candidate
        try:
            resolved = absolute.resolve()
        except (OSError, ValueError):
            return [], f"ERROR: path '{item}' could not be resolved."
        if resolved != root and not resolved.is_relative_to(root):
            return [], f"ERROR: path '{item}' escapes the project root."
        rel = "." if resolved == root else str(resolved.relative_to(root))
        if sandbox is not None and sandbox.is_forbidden(rel):
            return [], (
                f"ERROR: path '{rel}' is in this agent's forbidden_paths "
                f"sandbox: {sandbox.forbidden_paths}"
            )
        out.append(rel)
    return out, None


async def _resolve_ref(ref: str) -> tuple[str, str | None]:
    """Validate a user-supplied ref against the repo. Empty string = no ref."""
    ref = (ref or "").strip()
    if not ref:
        return "", None
    if (err := _reject_option_like(ref, "ref")) is not None:
        return "", err
    rc, _, stderr = await _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if rc != 0:
        # Ranges (a..b) don't resolve as a single commit; check them separately
        # rather than rejecting a legitimate diff range.
        if ".." in ref:
            rc2, _, _ = await _git("rev-parse", "--verify", "--quiet", ref.split("..", 1)[0])
            if rc2 == 0:
                return ref, None
        return "", f"ERROR: unknown ref '{ref}'. {stderr}".strip()
    return ref, None


class _GitTool(BaseTool):
    """Shared plumbing: sandbox injection and the not-a-repo guard."""

    def __init__(self, sandbox: SandboxPolicy | None = None) -> None:
        self._sandbox = sandbox

    async def _guard(self) -> str | None:
        if not await _is_repo():
            return (
                f"ERROR: {settings.project_root} is not a git repository — "
                "git tools are unavailable here."
            )
        return None


# ── Inspection ────────────────────────────────────────────────────────────

class GitStatusTool(_GitTool):
    name = "git_status"
    description = (
        "Show the working tree status: current branch, and which files are "
        "staged, modified, or untracked. Read-only. Use this before committing "
        "to see exactly what you changed."
    )
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        _, branch, _ = await _git("rev-parse", "--abbrev-ref", "HEAD")
        rc, porcelain, stderr = await _git("status", "--porcelain")
        if rc != 0:
            return f"ERROR: git status failed: {stderr}"
        if not porcelain.strip():
            return f"On branch {branch}\nWorking tree clean."

        staged, unstaged, untracked = [], [], []
        for line in porcelain.splitlines():
            if len(line) < 4:
                continue
            index_flag, tree_flag, path = line[0], line[1], line[3:].strip()
            if index_flag == "?" and tree_flag == "?":
                untracked.append(path)
                continue
            if index_flag != " ":
                staged.append(f"{index_flag} {path}")
            if tree_flag != " ":
                unstaged.append(f"{tree_flag} {path}")

        parts = [f"On branch {branch}"]
        for label, group in (
            ("Staged", staged), ("Not staged", unstaged), ("Untracked", untracked)
        ):
            if group:
                parts.append(f"\n{label} ({len(group)}):")
                parts.extend(f"  {entry}" for entry in group)
        return "\n".join(parts)


class GitDiffTool(_GitTool):
    name = "git_diff"
    description = (
        "Show what changed. With no 'paths' this returns a per-file summary "
        "(--stat) rather than the full patch, because a whole-tree diff can be "
        "tens of thousands of lines. Name 'paths' to get the actual patch for "
        "those files, or pass stat=false to force a full diff. Read-only. "
        "Use this to confirm an edit actually landed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to diff. Omit for a whole-tree summary.",
            },
            "staged": {
                "type": "boolean",
                "description": "Diff the staged changes instead of the working tree.",
                "default": False,
            },
            "ref": {
                "type": "string",
                "description": "Commit or range (e.g. 'HEAD~3' or 'main..HEAD') to diff against.",
            },
            "stat": {
                "type": "boolean",
                "description": "Summary only. Defaults to true when 'paths' is omitted.",
            },
        },
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        paths, perr = _normalize_paths(params.get("paths"), self._sandbox, require=False)
        if perr:
            return perr
        ref, rerr = await _resolve_ref(params.get("ref", ""))
        if rerr:
            return rerr

        stat = params.get("stat")
        if stat is None:
            stat = not paths

        args = ["diff"]
        if params.get("staged"):
            args.append("--cached")
        if ref:
            args.append(ref)
        args.append("--stat" if stat else "--patch")
        if paths:
            args.append("--")
            args.extend(paths)

        rc, out, stderr = await _git(*args, timeout=30.0)
        if rc != 0:
            return f"ERROR: git diff failed: {stderr}"
        if not out.strip():
            scope = f" for {', '.join(paths)}" if paths else ""
            return f"No changes{scope}."
        if stat:
            out += "\n\n(summary only — pass 'paths' to see the patch for specific files)"
        return out


class GitLogTool(_GitTool):
    name = "git_log"
    description = (
        "List recent commits (sha, date, author, subject). Read-only. "
        "Narrow with 'paths' to see the history of specific files."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Commits to show (default 20, max 200).", "default": 20},
            "paths": {"type": "array", "items": {"type": "string"}, "description": "Only commits touching these files."},
            "ref": {"type": "string", "description": "Branch or commit to log from (default: current HEAD)."},
        },
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        paths, perr = _normalize_paths(params.get("paths"), self._sandbox, require=False)
        if perr:
            return perr
        ref, rerr = await _resolve_ref(params.get("ref", ""))
        if rerr:
            return rerr
        try:
            limit = max(1, min(int(params.get("limit", 20)), 200))
        except (TypeError, ValueError):
            limit = 20

        args = ["log", f"--max-count={limit}", "--pretty=format:%h  %ad  %an  %s", "--date=short"]
        if ref:
            args.append(ref)
        if paths:
            args.append("--")
            args.extend(paths)

        rc, out, stderr = await _git(*args)
        if rc != 0:
            return f"ERROR: git log failed: {stderr}"
        return out or "No commits found."


class GitShowTool(_GitTool):
    name = "git_show"
    description = (
        "Show one commit: its message and the diff it introduced. Read-only. "
        "Narrow with 'paths' when the commit is large."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Commit sha or ref to show."},
            "paths": {"type": "array", "items": {"type": "string"}, "description": "Limit the diff to these files."},
        },
        "required": ["ref"],
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        ref, rerr = await _resolve_ref(params.get("ref", ""))
        if rerr:
            return rerr
        if not ref:
            return "ERROR: 'ref' is required."
        paths, perr = _normalize_paths(params.get("paths"), self._sandbox, require=False)
        if perr:
            return perr

        args = ["show", ref, "--stat", "--patch"]
        if paths:
            args.append("--")
            args.extend(paths)
        rc, out, stderr = await _git(*args, timeout=30.0)
        if rc != 0:
            return f"ERROR: git show failed: {stderr}"
        return out or f"{ref} introduced no changes."


# ── Mutation ──────────────────────────────────────────────────────────────

class GitCommitTool(_GitTool):
    name = "git_commit"
    description = (
        "Stage the named files and commit them. 'paths' is REQUIRED and must "
        "name each file explicitly — this tool never stages by wildcard, so "
        "unrelated changes (including a human's concurrent edits) can never be "
        "swept into your commit. Run git_status or git_diff first to see what "
        "you actually changed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact files to stage and commit. Required, non-empty.",
            },
            "message": {"type": "string", "description": "Commit message."},
        },
        "required": ["paths", "message"],
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        message = str(params.get("message", "")).strip()
        if not message:
            return "ERROR: 'message' is required."
        paths, perr = _normalize_paths(params.get("paths"), self._sandbox, require=True)
        if perr:
            return perr

        rc, _, stderr = await _git("add", "--", *paths)
        if rc != 0:
            return f"ERROR: git add failed: {stderr}"

        # Commit only what we just staged. --only re-scopes the commit to these
        # pathspecs, so anything another writer staged in the meantime is left
        # in the index untouched rather than riding along.
        rc, out, stderr = await _git(
            "commit", "--only", "-m", message, "--", *paths, timeout=30.0
        )
        if rc != 0:
            detail = stderr or out
            if "nothing to commit" in detail or "no changes added" in detail:
                return f"Nothing to commit — {', '.join(paths)} matched no changes."
            return f"ERROR: git commit failed: {detail}"

        _, sha, _ = await _git("rev-parse", "--short", "HEAD")
        return f"Committed {len(paths)} path(s) as {sha}: {message}\n{out}"


class GitBranchTool(_GitTool):
    name = "git_branch"
    description = (
        "List branches, or create and/or switch to one. Switching is refused by "
        "git itself when it would clobber uncommitted work."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "switch", "create_and_switch"],
                "description": "What to do (default: list).",
                "default": "list",
            },
            "name": {"type": "string", "description": "Branch name. Required for anything but 'list'."},
        },
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        action = str(params.get("action", "list")).strip() or "list"
        if action == "list":
            rc, out, stderr = await _git("branch", "--list", "-vv")
            return out if rc == 0 else f"ERROR: git branch failed: {stderr}"

        name = str(params.get("name", "")).strip()
        if not name:
            return f"ERROR: 'name' is required for action '{action}'."
        if (err := _reject_option_like(name, "branch name")) is not None:
            return err
        rc, _, stderr = await _git("check-ref-format", "--branch", name)
        if rc != 0:
            return f"ERROR: '{name}' is not a valid branch name. {stderr}".strip()

        if action == "create":
            rc, out, stderr = await _git("branch", "--", name)
            return f"Created branch {name}." if rc == 0 else f"ERROR: {stderr or out}"
        if action == "switch":
            rc, out, stderr = await _git("switch", "--", name)
            return f"Switched to {name}.\n{stderr or out}".strip() if rc == 0 else f"ERROR: {stderr or out}"
        if action == "create_and_switch":
            rc, out, stderr = await _git("switch", "-c", name)
            return f"Created and switched to {name}.\n{stderr or out}".strip() if rc == 0 else f"ERROR: {stderr or out}"
        return f"ERROR: unknown action '{action}'."


class GitRestoreTool(_GitTool):
    name = "git_restore"
    description = (
        "Discard changes to the named files, restoring them from a commit "
        "(default HEAD). This is the undo for a bad edit. 'paths' is REQUIRED "
        "and explicit — it never restores the whole tree, so a concurrent "
        "editor's work is never discarded. THIS DESTROYS UNCOMMITTED CHANGES "
        "to the files you name; run git_diff first."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact files to restore. Required, non-empty.",
            },
            "ref": {"type": "string", "description": "Commit to restore from (default HEAD)."},
        },
        "required": ["paths"],
    }

    async def execute(self, **params: Any) -> str:
        if (err := await self._guard()) is not None:
            return err
        paths, perr = _normalize_paths(params.get("paths"), self._sandbox, require=True)
        if perr:
            return perr
        ref, rerr = await _resolve_ref(params.get("ref", ""))
        if rerr:
            return rerr

        args = ["restore", "--source", ref or "HEAD", "--staged", "--worktree", "--", *paths]
        rc, out, stderr = await _git(*args, timeout=30.0)
        if rc != 0:
            return f"ERROR: git restore failed: {stderr or out}"
        return f"Restored {len(paths)} path(s) from {ref or 'HEAD'}: {', '.join(paths)}"
