"""Project frontend commands work through real agent execution boundaries."""
import json
import shutil
from types import SimpleNamespace

import pytest
from app.config import settings
from app.utils.tools import SandboxPolicy, _parse_sandbox_policy, project_shell_arguments
from app.utils.tools import javascript_execution as js, process_sandbox, shell
from app.utils.tools.security_policy import hardcoded_check, _safe_frontend_shell


@pytest.mark.parametrize('command', ['npm --prefix app/frontend run build',
    'cd app/frontend && npm run build', 'pnpm --dir app/frontend build',
    'npm ci', 'npm install', 'yarn build', 'bun run build', 'node --version'])
def test_project_build_commands_are_allowed(command):
    for agent in ('builder', 'keeper'):
        assert _parse_sandbox_policy(settings.agents_dir / agent).is_shell_allowed(command)
        assert hardcoded_check('shell_exec', {'command': command}, agent)[0] == 'allow'


@pytest.mark.parametrize('command', ['npm publish', 'npm install -g vite',
    'npm --prefix /tmp/other install', 'cd ../../ && npm install',
    'npm run build && rm -rf /', 'npm install --prefix=../../outside'])
def test_unrelated_commands_are_not_blessed(command):
    assert not _safe_frontend_shell({'command': command})
    assert hardcoded_check('shell_exec', {'command': command}, 'keeper')[0] != 'allow'


def test_managed_runtime_discovery_preserves_package_files(tmp_path, monkeypatch):
    runtime = tmp_path / 'mise' / 'node' / 'v22'
    (runtime / 'bin').mkdir(parents=True)
    (runtime / 'bin/node').write_text('node fixture')
    package = runtime / 'lib/node_modules/npm'
    (package / 'bin').mkdir(parents=True)
    (package / 'package.json').write_text('{"name":"npm"}')
    (package / 'bin/npm-cli.js').write_text('npm fixture')
    (runtime / 'bin/npm').symlink_to(package / 'bin/npm-cli.js')
    monkeypatch.setattr(js.shutil, 'which', lambda name: str(runtime / 'bin' / name) if name in {'node', 'npm'} else None)
    found = js.installations()
    assert found['node'][1] == runtime / 'bin/node'
    assert found['npm'][1] == package
    assert tmp_path not in {source for _, source in found.values()}


def test_cd_prefix_and_quoted_directories():
    assert project_shell_arguments('cd "front end" && npm run build') == ('front end', ['npm', 'run', 'build'])
    with pytest.raises(ValueError):
        project_shell_arguments('cd app && npm run build; touch other')


async def test_syntax_error_does_not_claim_allowed_executable_is_missing():
    result = await shell.ShellExecTool(SandboxPolicy(shell_allowlist=['node', 'npm'])).execute(command='node --version; npm --version')
    assert 'Unsupported shell syntax' in result
    assert 'not in this agent' not in result


async def test_actual_npm_build_with_private_cache_and_large_descriptor_budget(tmp_path, monkeypatch):
    if not all(shutil.which(name) for name in ('bwrap', 'prlimit', 'node', 'npm')):
        pytest.skip('JavaScript isolation runtime unavailable')
    project = tmp_path / 'project'
    frontend = project / 'front end'
    frontend.mkdir(parents=True)
    (frontend / 'package.json').write_text(json.dumps({'private': True, 'scripts': {'build': 'node build.cjs'}}))
    (frontend / 'build.cjs').write_text('''
const fs = require('fs');
if (process.env.GITHUB_TOKEN) throw Error('credential inherited');
const descriptors = Array.from({length: 1500}, () => fs.openSync('package.json','r'));
fs.mkdirSync('dist', {recursive:true});
fs.writeFileSync('dist/index.html', 'built in sandbox');
for (const descriptor of descriptors) fs.closeSync(descriptor);
console.log('FRONTEND_BUILD_OK');
''')
    monkeypatch.setenv('GITHUB_TOKEN', 'synthetic-private')
    monkeypatch.setattr(shell, 'settings', SimpleNamespace(project_root=project, max_shell_timeout=30))
    tool = shell.ShellExecTool(SandboxPolicy(shell_allowlist=['npm']))
    result = await tool.execute(command='cd "front end" && npm run build')
    assert 'FRONTEND_BUILD_OK' in result and 'Exit code: 0' in result, result
    assert (frontend / 'dist/index.html').read_text() == 'built in sandbox'
    assert 'escapes project root' in await tool.execute(command='cd ../ && npm run build')


def test_python_limits_remain_separate_from_shell(tmp_path):
    if not all(shutil.which(name) for name in ('bwrap', 'prlimit')):
        pytest.skip('isolation unavailable')
    assert '--as=1073741824' in process_sandbox.command(tmp_path, ['python', '--version'])
    args = process_sandbox.command(tmp_path, ['node', '--version'], profile='shell')
    assert not any(arg.startswith('--as=') for arg in args)
    assert '--nofile=65536' in args


def test_standalone_pnpm_includes_adjacent_modules(tmp_path, monkeypatch):
    runtime = tmp_path / 'pnpm' / '11'
    (runtime / 'dist').mkdir(parents=True)
    (runtime / 'pnpm').write_bytes(b'fixture binary')
    (runtime / 'dist/pnpm.mjs').write_text('// fixture')
    monkeypatch.setattr(js.shutil, 'which', lambda name: str(runtime / 'pnpm') if name == 'pnpm' else None)
    assert js.installations()['pnpm'] == (runtime / 'pnpm', runtime)
