# Execution and credential boundaries

Agent `execute_code` and `shell_exec` now require Linux with **bubblewrap**
(`bwrap`) and util-linux (`prlimit`). Install these OS packages before using
execution tools, for example `sudo apt-get install bubblewrap util-linux` on
Debian/Ubuntu or `sudo pacman -S bubblewrap util-linux` on Arch.
The host must permit unprivileged user namespaces. If isolation cannot start,
the tools refuse execution; there is no unrestricted fallback. Other YAPOC
features remain available, including on platforms without these facilities.

Each command gets a separate mount, PID, IPC and user namespace.
The project appears at `/work`; Python's standard library and installed
runtime are read-only. Ordinary project writes persist. Per-agent forbidden
paths, `app/config`, the security agent, and the sandbox implementation are
read-only. Known credential stores (including `.env`, token JSON files, SSH
keys and `.git`) are hidden. Parent environment variables are not inherited.
Temporary files live in a private `/tmp`. Shell and Python tools share host networking by default, including DNS and
HTTPS trust stores. Set `EXECUTION_NETWORK_ENABLED=false` and restart to
explicitly isolate networking for all execution, including Poetry. Shared
networking also permits connections to host-local services. Credentials and
parent environment variables remain hidden.

Use native integration tools for authenticated GitHub/email operations and
native Git tools for repository history operations. Shell allowlists use exact
executable names. A leading `cd directory && command` is supported, as is the
`cwd` tool parameter. Other chaining, pipelines, substitution and redirection
are rejected with a syntax error rather than a misleading allowlist error. An empty
shell allowlist still permits shell syntax **inside OS isolation**.

## Poetry environments outside the repository

The host Poetry executable is discovered from PATH and its dedicated runtime
is mounted read-only (official installer, pipx, mise, or system `/usr` layouts).
YAPOC's current Python virtualenv is treated as the project's managed runtime;
its location may be outside the repository. No repository owner, home path or
environment name is hard-coded.

Keeper, builder and master may run validated `poetry --version`, `poetry env
info --path`, `poetry check`, `poetry show`, and dependency commands (`install`,
`sync`, `lock`, `add`, `remove`, `update`) without an LLM review. The agent must
still have `shell_exec` and a matching executable allowlist. `ls` may inspect
the exact managed runtime or Poetry installation; parent directories and
unrelated home paths remain forbidden.

Dependency operations get a writable **project virtualenv**,
and a private package cache. Installation runs serially to stay within the
process memory limit. Poetry plugins, keyring lookup and implicit
virtualenv creation are disabled. `VIRTUAL_ENV` identifies the mounted project
environment. Dependency commands see the project at its real path so editable
installation remains usable by the host backend; other commands use `/work`.
Alternate project directories, arbitrary URLs/local package
paths and unrecognized flags do not receive this exception. `poetry run`
keeps the ordinary read-only environment and configured network policy; it cannot use
the dependency exception to execute arbitrary commands on the host.

Examples: `poetry install --no-interaction`, `poetry lock`, and `poetry install
--dry-run --no-root`. A stale-lock error means the command reached Poetry:
update the lockfile with `poetry lock` before installing. Missing Poetry is
reported as unavailable; there is no unrestricted fallback.

Python execution limits: 1 GiB virtual address space, 120 CPU seconds, 64 MiB per
output file and 128 descriptors. Shell execution allows 65,536 descriptors,
1 GiB per output file and CPU time up to `MAX_SHELL_TIMEOUT` (default 600 seconds).
Shell address space is uncapped by default because modern JavaScript runtimes
reserve large virtual ranges; `SHELL_MEMORY_LIMIT_MB` can opt into a cap. This
is an address-space limit, not a physical-memory quota. Node's default heap limit
in the sandbox is 4 GiB. Shell wall timeout defaults to 300 seconds for JavaScript
commands and 30 seconds otherwise. Both tools bound combined stdout/stderr to
200,000 bytes. Overflow, cancellation and timeout kill and reap the
process group. These limits do not constitute an aggregate disk or process
quota; generated code remains trusted to make authorized project changes.

`file_read` rejects credential paths and aliases resolving to them. Tool
results are scrubbed before model/event delivery and capped at 20,000
characters by default. File reads are also scrubbed for direct callers.
Configured credentials and recognized GitHub token formats are redacted;
GitHub UI file content is redacted after Base64 decoding as well.
Redaction cannot identify every arbitrary secret embedded in ordinary files.

The security gate denies execution when review fails, including provider
outages. Deterministically allowed read tools continue without an LLM review.
`execute_code` now requires security classification. Audit text is scrubbed.

After updating the backend, restart with `poetry run yapoc restart` (or restart
the existing supervisor service). Existing backend and agent processes need
to load the new code. Validate with:

```sh
poetry run pytest tests/test_execution_security.py tests/test_sandbox.py tests/test_security_policy.py -q
poetry run pytest tests/ app/backend/tests/ -q
pnpm --dir app/frontend build
```

The isolation tests use temporary synthetic credentials; no real GitHub token
or network connection is required. Missing OS dependencies produce explicit
test skips, while the production tool fails closed.


## Frontend build tools

Installed Node, npm, npx, pnpm, yarn, corepack and bun executables are exposed
through `/run/javascript`. Only resolved binaries and their companion package
files are mounted, including version-manager installations outside the project.
No Node version or user path is hard-coded. The backend must start with these
tools on its host PATH. Docker images include Node/npm and corepack shims from
the frontend build stage. Package caches live in private `/tmp` directories.

Builder and keeper allowlists include the frontend toolchain. Master, builder
and keeper can run project-local package installation, build, test, lint and
format commands without an extra model review. Publishing and global installation
are not part of this automatic allowance. File protections and credential masks
still apply.

Examples through `shell_exec`:

- `npm --prefix app/frontend run build`
- `npm run build` with `cwd="app/frontend"`
- `cd app/frontend && pnpm run build`
- `node --version` or `npm --version` as separate calls

Restart the backend and its agent workers after updating execution configuration.
A Node package manager installed after backend startup may require restarting
from a terminal whose PATH contains it.
