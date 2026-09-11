"""Expose installed JavaScript executables and their packages, not host homes."""
from pathlib import Path
import shutil

NAMES = ('node', 'npm', 'npx', 'pnpm', 'yarn', 'corepack', 'bun')


def installations() -> dict[str, tuple[Path, Path]]:
    found = {}
    for name in NAMES:
        location = shutil.which(name)
        if not location:
            continue
        executable = Path(location).resolve()
        if not executable.is_file():
            continue
        # JS launchers import neighboring package files. Standalone binaries
        # need only their own file. Never bind ~/.local/bin or the whole home.
        source = executable
        if name not in {'node', 'bun'}:
            for parent in list(executable.parents)[:5]:
                if (parent / 'package.json').is_file():
                    source = parent
                    break
        # Standalone pnpm embeds Node but loads its adjacent dist/pnpm.mjs.
        if name == 'pnpm' and (executable.parent / 'dist' / 'pnpm.mjs').is_file():
            source = executable.parent
        found[name] = executable, source
    return found


def executable_name(argv: list[str]) -> str | None:
    if not argv:
        return None
    if argv[0] in NAMES:
        return argv[0]
    for name, (executable, _) in installations().items():
        if argv[0] == str(executable):
            return name
    return None


def project_operation(argv: list[str]) -> bool:
    """Routine local install/build/test operations; publishing gets normal review."""
    name = executable_name(argv)
    args = argv[1:]
    if not name or not args:
        return False
    # No global installs, publishing, or arbitrary runtime commands are blessed.
    if any(arg in {'-g', '--global', 'publish', 'login', 'logout', 'config'} for arg in args):
        return False
    if args in [['--version'], ['-v']]:
        return True
    if name not in {'npm', 'pnpm', 'yarn', 'bun'}:
        return False
    # Prefix/cwd flags are permitted only for paths inside the project. The
    # security policy validates all argument paths before this predicate.
    while len(args) >= 2 and args[0] in {'--prefix', '--dir', '-C', '--cwd'}:
        args = args[2:]
    if not args:
        return False
    if args[0] in {'install', 'ci', 'add', 'remove', 'uninstall', 'update', 'rebuild'}:
        return True
    if args[0] in {'run', 'run-script'}:
        args = args[1:]
    return bool(args and args[0] in {'build', 'test', 'lint', 'typecheck', 'type-check', 'check', 'format'})
