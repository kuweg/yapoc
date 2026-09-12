"""Execution boundary shared by agent shell/Python tools.

On Linux, bubblewrap supplies mount, PID, IPC, user and network namespaces:
only the project and language runtime are visible, and credentials plus
policy-protected paths are overmounted. That path is **fail-closed** — if
bwrap or prlimit is missing on a Linux host, execution is refused rather than
downgraded. ``SANDBOX_REQUIRED`` encodes that.

Platforms with no bubblewrap equivalent (macOS, Windows) cannot offer the
boundary at all. There the tools run the command directly, with NO isolation:
full host environment, full filesystem access, real network. Callers must
treat that as running the code as the user, because that is what it is.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import signal
import sys

from app.config import settings
from app.utils.secrets import credential_path


# Distinguishes "caller said inherit the host env" (None) from "caller said
# nothing", which must keep the empty-env default the sandbox relies on.
_INHERIT_NOTHING: dict[str, str] = {}


class SandboxUnavailable(RuntimeError):
    pass


# Platforms where a sandbox is mandatory. Linux can always provide one, so a
# missing bwrap/prlimit there is a broken install, not a platform limit — and
# must fail closed rather than silently dropping isolation. Keep the fallback
# in the tools keyed on THIS, never on SANDBOX_AVAILABLE alone.
SANDBOX_REQUIRED: bool = sys.platform == 'linux'


def sandbox_available() -> bool:
    """True when an isolated run is possible right now.

    Note this is NOT the fallback condition — a Linux host missing bwrap is a
    broken install and must still refuse to run. See ``SANDBOX_REQUIRED``.
    """
    return (
        sys.platform == 'linux'
        and bool(shutil.which('bwrap'))
        and bool(shutil.which('prlimit'))
    )


# Snapshot for callers that just want to branch on it. PATH is fixed for a
# process's life in practice; use sandbox_available() if you need a live read.
SANDBOX_AVAILABLE: bool = sandbox_available()


def command(root: Path, argv: list[str], *, forbidden=(), cwd: str = '.', bindings=(), poetry_mode=None, profile="python") -> list[str]:
    bwrap = shutil.which('bwrap')
    prlimit = shutil.which('prlimit')
    if sys.platform != 'linux' or not bwrap or not prlimit:
        raise SandboxUnavailable('Isolated execution requires Linux, bubblewrap and util-linux (prlimit).')
    root = root.resolve()
    work = (root / cwd).resolve()
    if not work.is_relative_to(root):
        raise SandboxUnavailable('Working directory escapes project root.')
    args = [bwrap, '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--clearenv']
    from .poetry_execution import installation, managed_environment
    poetry = installation()
    environment = managed_environment()
    dependencies = poetry_mode == 'dependencies'
    if dependencies:
        if environment == Path(sys.base_prefix).resolve():
            raise SandboxUnavailable('Poetry dependency operations require a project virtualenv.')
    if settings.execution_network_enabled:
        args += ['--share-net']
    # No home directory, host /proc, /run, sockets, or inherited descriptors.
    for path in ('/usr', '/bin', '/sbin', '/lib', '/lib64'):
        p = Path(path)
        if p.is_symlink():
            args += ['--symlink', os.readlink(p), path]
        elif p.exists():
            args += ['--ro-bind', path, path]
    args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/run']
    for path in sorted({Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), environment}, key=str):
        if path != Path('/usr') and not path.is_relative_to('/usr') and not path.is_relative_to(root):
            args += ['--bind' if dependencies and path == environment else '--ro-bind', str(path), str(path)]
    if poetry:
        # Runtime only, never the user's home/config directory. Include the
        # interpreter target for venvs whose Python is an external symlink.
        launcher, runtime = poetry
        if runtime != Path('/usr') and not runtime.is_relative_to('/usr'):
            args += ['--ro-bind', str(runtime), str(runtime)]
        interpreter = runtime / 'bin' / 'python'
        if interpreter.exists():
            base = interpreter.resolve().parent.parent
            if base != runtime and base != Path('/usr') and not base.is_relative_to('/usr'):
                args += ['--ro-bind', str(base), str(base)]
    from .javascript_execution import installations
    javascript = installations()
    for _, source in javascript.values():
        if not source.is_relative_to('/usr') and not source.is_relative_to(root):
            args += ['--ro-bind', str(source), str(source)]
    # Stable executable names even when npm/pnpm resolve to JS entrypoints.
    args += ['--dir', '/run/javascript']
    for name, (executable, _) in javascript.items():
        destination = (str(root) if dependencies else '/work') + '/' + executable.relative_to(root).as_posix() if executable.is_relative_to(root) else str(executable)
        args += ['--symlink', destination, '/run/javascript/' + name]
    if settings.execution_network_enabled:
        # Share host DNS and public trust stores without exposing private keys.
        for path in ('/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf',
                     '/etc/gai.conf', '/etc/ssl/certs', '/etc/ca-certificates',
                     '/etc/ssl/cert.pem'):
            if Path(path).exists():
                args += ['--ro-bind', path, path]
    # Editable installs must record the real project path in the shared
    # virtualenv, not the sandbox-only /work alias.
    sandbox_root = str(root) if dependencies else '/work'
    args += ['--bind', str(root), sandbox_root]
    # Hide credential stores including ignored files. Do not follow symlinks:
    # targets outside /work are absent; targets inside are masked at source.
    hidden = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            path = Path(base) / name
            rel = path.relative_to(root)
            if credential_path(rel):
                if path.is_symlink():
                    raise SandboxUnavailable('Credential symlink requires removal before isolated execution.')
                hidden.append((path, rel))
                if name in dirs:
                    dirs.remove(name)
        # Dependencies contain no user configuration and scanning them is costly.
        dirs[:] = [name for name in dirs if name not in {'node_modules', '.venv', '__pycache__'}]
    protected = list(forbidden) + ['app/agents/security', 'app/config', 'app/utils/tools/process_sandbox.py']
    if not dependencies:
        protected.append('.venv')
    for raw in protected:
        p = (root / raw).resolve()
        if not p.is_relative_to(root):
            raise SandboxUnavailable('Invalid forbidden path.')
        if raw in forbidden and not p.exists():
            raise SandboxUnavailable('A forbidden path is missing; refusing an incomplete sandbox.')
        if p.exists():
            dest = sandbox_root + '/' + p.relative_to(root).as_posix()
            # Credential masks below take precedence over these mounts.
            args += ['--ro-bind', str(p), dest]
    for path, rel in hidden:
        dest = sandbox_root + '/' + rel.as_posix()
        if path.is_dir():
            args += ['--tmpfs', dest, '--remount-ro', dest]
        else:
            args += ['--ro-bind', '/dev/null', dest]
    for source, destination in bindings:
        args += ['--ro-bind', str(source), destination]
    executable = Path(sys.executable)
    if executable.is_relative_to(root):
        sandbox_python = sandbox_root + '/' + executable.relative_to(root).as_posix()
        argv = [sandbox_python if item == sys.executable else item for item in argv]
        python_bin = str(Path(sandbox_python).parent)
    else:
        python_bin = str(executable.parent)
    if poetry:
        python_bin += ':' + str(poetry[0].parent)
    if poetry_mode:
        if not poetry:
            raise SandboxUnavailable('Poetry is not installed on the host.')
        argv = [str(poetry[0]), '--no-plugins', *argv[1:]]
        venv = sandbox_root + '/' + environment.relative_to(root).as_posix() if environment.is_relative_to(root) else str(environment)
        args += ['--setenv', 'VIRTUAL_ENV', venv, '--setenv', 'POETRY_VIRTUALENVS_CREATE', 'false',
                 '--setenv', 'POETRY_CACHE_DIR', '/tmp/poetry-cache', '--setenv', 'POETRY_KEYRING_ENABLED', 'false',
                 '--setenv', 'POETRY_INSTALLER_PARALLEL', 'false']
    limits = ['--as=1073741824', '--cpu=120', '--fsize=67108864', '--nofile=128']
    if profile == 'shell':
        limits = [f'--cpu={settings.max_shell_timeout}', '--fsize=1073741824', '--nofile=65536']
        if settings.shell_memory_limit_mb:
            limits.insert(0, f'--as={settings.shell_memory_limit_mb * 1024 * 1024}')
    args += ['--setenv', 'npm_config_update_notifier', 'false',
             '--setenv', 'npm_config_cache', '/tmp/npm-cache',
             '--setenv', 'COREPACK_HOME', '/tmp/corepack', '--setenv', 'XDG_CACHE_HOME', '/tmp/cache',
             '--setenv', 'NODE_OPTIONS', '--jitless',
             '--setenv', 'PATH', f'{python_bin}:/run/javascript:/usr/bin:/bin',
             '--setenv', 'HOME', '/tmp', '--setenv', 'LANG', 'C.UTF-8',
             '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
             '--chdir', sandbox_root + '/' + work.relative_to(root).as_posix(), '--',
             prlimit, *limits, '--', *argv]
    return args


async def run(
    argv: list[str],
    timeout: int,
    cap: int = 200_000,
    *,
    env: dict[str, str] | None = _INHERIT_NOTHING,
    cwd: str | Path | None = None,
) -> tuple[int, str, str]:
    """Read concurrently with a shared byte budget; kill and reap on every exit.

    ``env`` defaults to an empty mapping, matching the bubblewrap path where
    the sandbox supplies the whole environment. Pass ``env=None`` to inherit
    the host environment — only correct for an unsandboxed run, which is
    already running as the user.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={} if env is _INHERIT_NOTHING else env,
        cwd=str(cwd) if cwd else None,
        start_new_session=True,
    )
    total = 0
    async def read(stream):
        nonlocal total
        result = bytearray()
        while chunk := await stream.read(8192):
            total += len(chunk)
            if total > cap:
                raise SandboxUnavailable('Process output exceeded the byte limit.')
            result.extend(chunk)
        return result.decode('utf-8', errors='replace')
    tasks = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr))]
    try:
        async with asyncio.timeout(timeout):
            out, err = await asyncio.gather(*tasks)
            await proc.wait()
        return proc.returncode, out, err
    finally:
        # Also terminate descendants which close stdout and outlive their parent.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Drain pipe buffers after killing; waiting with paused, unread pipes
        # can otherwise deadlock asyncio's subprocess transport.
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except TimeoutError:
            if proc.stdout:
                proc.stdout._transport.close()
            if proc.stderr:
                proc.stderr._transport.close()
        await proc.wait()
