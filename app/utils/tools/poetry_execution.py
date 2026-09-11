"""Narrow Poetry exception for the project's managed Python environment."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys


def installation() -> tuple[Path, Path] | None:
    executable = shutil.which('poetry')
    if not executable:
        return None
    path = Path(executable).resolve()
    # pipx, mise and official-install layouts all use <runtime>/bin/poetry.
    runtime = path.parent.parent
    if not runtime.is_relative_to('/usr') and not (runtime / 'pyvenv.cfg').is_file():
        return None  # Never expose a whole ~/.local directory as a runtime.
    return path, runtime


def managed_environment() -> Path:
    return Path(sys.prefix).resolve()


def operation(argv: list[str]) -> str | None:
    """Classify only exact commands; arbitrary flags/locations are refused."""
    if not argv:
        return None
    found = installation()
    if argv[0] != 'poetry' and (not found or Path(argv[0]).resolve() != found[0]):
        return None
    args = argv[1:]
    if args in (['--version'], ['-V'], ['env', 'info'], ['env', 'info', '--path'],
                ['env', 'info', '--executable'], ['env', 'list'], ['env', 'list', '--full-path']):
        return 'read'
    if not args or args[0] not in {'install', 'sync', 'lock', 'add', 'remove', 'update', 'check', 'show', 'run'}:
        return None
    verb, rest = args[0], args[1:]
    # `run` never gets the network/write exception: arbitrary programs execute
    # with the ordinary read-only runtime and configured networking.
    if verb == 'run':
        return 'run' if rest else None
    switches = {'--no-interaction', '-n', '--no-root', '--no-directory', '--dry-run',
                '--sync', '--all-groups', '--all-extras', '--compile', '--strict',
                '--lock', '--tree', '--latest', '--outdated', '--why', '-v', '-vv', '-vvv',
                '--dev', '-D', '--optional', '--regenerate'}
    valued = {'--with', '--without', '--only', '--group', '-G', '--extras', '-E'}
    waiting = False
    for arg in rest:
        if waiting:
            if not re.fullmatch(r'[A-Za-z0-9_,.-]+', arg):
                return None
            waiting = False
        elif arg in valued:
            waiting = True
        elif arg in switches:
            continue
        elif verb in {'add', 'remove', 'update', 'show'} and not arg.startswith('-') and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.\[\],<>=!~^*+-]*', arg):
            continue
        else:
            return None
    if waiting:
        return None
    return 'read' if verb in {'check', 'show'} else 'dependencies'


def safe_inspection(argv: list[str]) -> bool:
    """Permit listing the exact runtime, not arbitrary home-directory access."""
    if not argv or argv[0] != 'ls':
        return False
    found = installation()
    roots = [managed_environment()]
    if found:
        roots.append(found[1])
    paths = []
    for arg in argv[1:]:
        if arg.startswith('-'):
            if not re.fullmatch(r'-[lahd]+', arg):
                return False
        else:
            path = Path(arg)
            if not path.is_absolute() or not any(path.resolve().is_relative_to(root) for root in roots):
                return False
            paths.append(path)
    return bool(paths)
