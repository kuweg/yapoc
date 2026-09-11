"""Poetry may manage this project's external venv without opening the home directory."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import venv

import pytest

from app.utils.tools import SandboxPolicy
from app.utils.tools import poetry_execution, process_sandbox, shell
from app.utils.tools.security_policy import hardcoded_check


@pytest.mark.parametrize('command', ['poetry --version', 'poetry env info --path',
    'poetry install', 'poetry install --no-interaction --with dev', 'poetry lock',
    'poetry add httpx', 'poetry remove httpx', 'poetry update httpx'])
def test_keeper_poetry_is_authorized(command):
    assert hardcoded_check('shell_exec', {'command': command}, 'keeper')[0] == 'allow'


@pytest.mark.parametrize('argv', [
    ['poetry', 'install', '--directory', '/tmp/other'], ['poetry', 'add', '../other'],
    ['poetry', 'self', 'update'], ['poetry', 'config', 'http-basic.repo', 'user', 'password'],
])
def test_arbitrary_poetry_targets_get_no_privileged_profile(argv):
    assert poetry_execution.operation(argv) is None


def test_runtime_inspection_is_narrow(tmp_path, monkeypatch):
    runtime = tmp_path / 'managed-env'
    runtime.mkdir()
    monkeypatch.setattr(poetry_execution, 'managed_environment', lambda: runtime)
    assert hardcoded_check('shell_exec', {'command': f'ls -la {runtime}/bin'}, 'keeper')[0] == 'allow'
    assert hardcoded_check('shell_exec', {'command': f'ls -la {tmp_path}'}, 'keeper')[0] == 'deny'
    assert hardcoded_check('shell_exec', {'command': f'ls -la {runtime}/../'}, 'keeper')[0] == 'deny'


def test_poetry_run_does_not_bypass_destruction_checks():
    assert hardcoded_check('shell_exec', {'command': 'poetry run rm -rf /'}, 'keeper')[0] == 'deny'
    assert not SandboxPolicy(shell_allowlist=['poetry']).is_shell_allowed('poetry --version; touch bypass')


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("mode", [None, "read", "dependencies", "run"])
def test_profiles_respect_configured_network_policy(tmp_path, monkeypatch, enabled, mode):
    if not shutil.which('bwrap') or not shutil.which('prlimit') or not poetry_execution.installation():
        pytest.skip('Poetry isolation runtime unavailable')
    monkeypatch.setattr(process_sandbox.settings, 'execution_network_enabled', enabled)
    monkeypatch.setattr(poetry_execution, 'managed_environment', lambda: tmp_path / 'external-env')
    args = process_sandbox.command(tmp_path, ['poetry', '--version'], poetry_mode=mode)
    assert ('--share-net' in args) is enabled
    assert ('/etc/resolv.conf' in args) is enabled
    if mode:
        assert '--no-plugins' in args


async def test_actual_install_into_external_virtualenv(tmp_path, monkeypatch):
    if not shutil.which('bwrap') or not shutil.which('prlimit') or not poetry_execution.installation():
        pytest.skip('Poetry isolation runtime unavailable')
    project = tmp_path / 'project'
    environment = tmp_path / 'external-virtualenv'
    project.mkdir()
    (project / 'app' / 'config').mkdir(parents=True)
    (project / '.env').write_text('SYNTHETIC_SECRET=hidden')
    venv.EnvBuilder(with_pip=False).create(environment)
    (project / 'fixture_package').mkdir()
    (project / 'fixture_package' / '__init__.py').write_text('')
    (project / 'pyproject.toml').write_text(
        '[project]\nname="fixture-package"\nversion="0.1.0"\n'
        'requires-python=">=3.12"\ndependencies=[]\n')
    monkeypatch.setattr(poetry_execution, 'managed_environment', lambda: environment)
    monkeypatch.setattr(shell, 'settings', SimpleNamespace(project_root=project, max_shell_timeout=30))
    tool = shell.ShellExecTool(SandboxPolicy(shell_allowlist=['poetry']))
    info = await tool.execute(command='poetry env info --path')
    assert str(environment) in info and 'Exit code: 0' in info, info
    for command in ['poetry lock', 'poetry install --no-interaction']:
        result = await tool.execute(command=command, timeout=30)
        assert 'Exit code: 0' in result, result
    assert (project / 'poetry.lock').is_file()
    assert list(environment.rglob('fixture_package-0.1.0.dist-info'))
    editable_paths = list(environment.rglob('fixture_package.pth'))
    assert editable_paths and str(project) in editable_paths[0].read_text()
    assert '/work' not in editable_paths[0].read_text()
    result = await tool.execute(command='poetry run python -c "from pathlib import Path; import sys; Path(sys.prefix, \'blocked\').write_text(\'bad\')"')
    assert 'Exit code: 0' not in result
    assert not (environment / 'blocked').exists()
