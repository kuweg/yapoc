"""Opt-in experiments. No dispatcher, named-agent slots, or user index mutations."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import sys
import uuid
from datetime import datetime, timezone
from app.config import settings
from app.utils.secrets import credential_path, scrub

ACTIVE = {'preparing', 'running', 'checking'}
_jobs: dict[str, asyncio.Task] = {}
_processes: dict[str, asyncio.subprocess.Process] = {}
_lock = asyncio.Lock()
_integrating: set[str] = set()


def home() -> Path:
    return settings.project_root / 'data' / 'universes'


def now():
    return datetime.now(timezone.utc).isoformat()


def folder(mid: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{32}', mid):
        raise ValueError('Invalid comparison ID.')
    return home() / mid


def write(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)


async def git(root: Path, *args: str, env=None, data: bytes | None = None) -> bytes:
    proc = await asyncio.create_subprocess_exec('git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_AUTHOR_NAME': 'YAPOC',
             'GIT_AUTHOR_EMAIL': 'yapoc@localhost', 'GIT_COMMITTER_NAME': 'YAPOC',
             'GIT_COMMITTER_EMAIL': 'yapoc@localhost', **(env or {})},
        stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(data), 60)
    except BaseException:
        proc.kill(); await proc.wait(); raise
    if proc.returncode:
        raise ValueError('Git operation failed. Check repository state and retained comparison files.')
    return out


def excluded(name: str) -> bool:
    return credential_path(name) or name.startswith(('data/', 'app/memory/', '.pnpm-store/')) or (
        name.startswith('app/agents/') and name.rsplit('/', 1)[-1] not in {'CONFIG.yaml', 'PROMPT.MD', 'agent.py', '__init__.py'})


async def stage_allowed(root: Path, env=None):
    names = set((await git(root, 'ls-files', '-c', '-o', '--exclude-standard', '-z', env=env)).decode().split('\0'))
    allowed = sorted(n for n in names if n and not excluded(n))
    if allowed:
        await git(root, 'add', '-A', '--pathspec-from-file=-', '--pathspec-file-nul', env=env,
                  data=('\0'.join(allowed) + '\0').encode())
    hidden = sorted(n for n in names if n and excluded(n))
    if hidden:
        await git(root, 'update-index', '--force-remove', '-z', '--stdin', env=env,
                  data=('\0'.join(hidden) + '\0').encode())


async def snapshot(root: Path, directory: Path) -> tuple[str, str]:
    """Use a private index, capturing tracked and nonignored working changes."""
    head = (await git(root, 'rev-parse', 'HEAD')).decode().strip()
    index = directory / 'snapshot.index'
    env = {'GIT_INDEX_FILE': str(index)}
    await git(root, 'read-tree', head, env=env)
    await stage_allowed(root, env=env)
    tree = (await git(root, 'write-tree', env=env)).decode().strip()
    commit = (await git(root, 'commit-tree', tree, '-p', head, '-m', 'YAPOC universe baseline')).decode().strip()
    index.unlink(missing_ok=True)
    return head, commit


def read(mid: str) -> dict:
    directory = folder(mid)
    result = json.loads((directory / 'mission.json').read_text())
    if result.get('integration') and result['integration'].get('status') == 'checking':
        if mid not in _integrating: result['integration']['status'] = 'interrupted'
    result['runs'] = []
    for letter in ('a', 'b'):
        state = json.loads((directory / letter / 'state.json').read_text())
        if state['status'] in ACTIVE and f'{mid}-{letter}' not in _jobs:
            state['status'] = 'interrupted'
            state['summary'] = 'Backend restarted; partial files and activity are retained.'
        from .preview import preview_url
        state['preview_url'] = preview_url(f'{mid}-{letter}')
        state['preview_available'] = state['status'] == 'completed' and preview_directory(directory / letter / 'worktree') is not None
        result['runs'].append(state)
    return result


def listing(session_id: str | None = None) -> list[dict]:
    if not home().exists(): return []
    result = []
    for file in sorted(home().glob('*/mission.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        try:
            item = read(file.parent.name)
            if session_id is None or item['session_id'] == session_id: result.append(item)
        except (OSError, ValueError, KeyError, TypeError): continue
    return result


def run_path(mid: str, letter: str) -> Path:
    if letter not in {'a', 'b'}: raise ValueError('Unknown universe.')
    return folder(mid) / letter


def state_update(mid, letter, **changes):
    path = run_path(mid, letter) / 'state.json'
    state = json.loads(path.read_text())
    write(path, {**state, **changes, 'updated_at': now()})


async def create(request) -> dict:
    async with _lock:
        if any(not task.done() for task in _jobs.values()):
            raise ValueError('A comparison is already running. Stop it or wait before starting another.')
        root = settings.project_root.resolve()
        # Fail before creating files when isolation isn't supported on this host.
        from app.utils.tools.process_sandbox import command
        command(root, ['true'], profile='shell')
        from app.utils.agent_settings import resolve_agent
        config = resolve_agent('builder')
        if not config: raise ValueError('Configure the builder provider and model before starting.')
        from app.utils.adapters.models import ALL_PRICING
        if config['model'] not in ALL_PRICING:
            raise ValueError('Builder model pricing is unknown. Select a priced model before using spending limits.')
        mid = uuid.uuid4().hex
        directory = folder(mid); directory.mkdir(parents=True)
        head, baseline = await snapshot(root, directory)
        mission = {'id': mid, 'objective': request.objective, 'requirements': request.requirements,
                   'session_id': request.session_id, 'created_at': now(), 'head': head, 'baseline': baseline,
                   'minutes': request.minutes, 'budget_usd': request.budget_usd, 'check_command': request.check_command,
                   'integration': None}
        created = []
        try:
            for letter, approach in zip(('a', 'b'), request.approaches):
                control = directory / letter; control.mkdir()
                workspace = control / 'worktree'
                branch = f'yapoc/universe/{mid}/{letter}'
                await git(root, 'worktree', 'add', '-b', branch, str(workspace), baseline)
                created.append(workspace)
                write(control / 'request.json', {**mission, 'letter': letter, 'approach': approach,
                    'workspace': str(workspace), 'config': {k: config[k] for k in ('adapter', 'model', 'temperature', 'max_tokens') if k in config}})
                write(control / 'state.json', {'id': f'universe_{mid}_{letter}', 'letter': letter, 'approach': approach,
                    'status': 'preparing', 'branch': branch, 'summary': '', 'checks': [], 'cost_usd': 0,
                    'input_tokens': 0, 'output_tokens': 0, 'updated_at': now(), 'preview_url': None})
            write(directory / 'mission.json', mission)
        except BaseException:
            for workspace in created:
                try: await git(root, 'worktree', 'remove', '--force', str(workspace))
                except ValueError: pass
            raise
        for letter in ('a', 'b'):
            key = f'{mid}-{letter}'
            _jobs[key] = asyncio.create_task(execute(mid, letter), name=key)
        return read(mid)


async def execute(mid: str, letter: str):
    key = f'{mid}-{letter}'
    control = run_path(mid, letter)
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(sys.executable, str(settings.project_root / 'app/universe_entry.py'), 'worker', str(control),
            cwd=settings.project_root, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True)
        _processes[key] = proc
        request = json.loads((control / 'request.json').read_text())
        await asyncio.wait_for(proc.wait(), request['minutes'] * 60 + 15)
        state = json.loads((control / 'state.json').read_text())
        if proc.returncode or state['status'] in ACTIVE:
            state_update(mid, letter, status='failed', summary='Run stopped unexpectedly; partial files are retained.')
        if state['status'] == 'completed':
            await finish_run(mid, letter)
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await proc.wait()
        state_update(mid, letter, status='cancelled', summary='Stopped. Partial files and activity are retained.')
        raise
    except TimeoutError:
        if proc and proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await proc.wait()
        state_update(mid, letter, status='timeout', summary='Time limit reached. Partial files are retained.')
    except Exception:
        state_update(mid, letter, status='failed', summary='Run could not finish. Review retained activity.')
    finally:
        if proc:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await proc.wait()
        _processes.pop(key, None)
        _jobs.pop(key, None)


async def finish_run(mid, letter):
    control = run_path(mid, letter); workspace = control / 'worktree'
    # Remove sensitive additions from the candidate index, without deleting files.
    await stage_allowed(workspace)
    await git(workspace, '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '-m', f'Universe {letter.upper()} candidate')
    head = (await git(workspace, 'rev-parse', 'HEAD')).decode().strip()
    state_update(mid, letter, commit=head)
    from .preview import start_preview
    preview_root = preview_directory(workspace)
    url = start_preview(f'{mid}-{letter}', preview_root) if preview_root else None
    state_update(mid, letter, preview_url=url)


async def stop(mid: str, letter: str | None = None):
    read(mid)
    tasks = []
    for choice in (letter,) if letter else ('a', 'b'):
        run_path(mid, choice)
        task = _jobs.get(f'{mid}-{choice}')
        if task:
            task.cancel(); tasks.append(task)
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    return read(mid)


def activity(mid, letter):
    path = run_path(mid, letter) / 'events.jsonl'
    if not path.exists(): return []
    # The worker bounds this file; incomplete final lines are ignored.
    result = []
    for line in path.read_text().splitlines()[-200:]:
        try: result.append(json.loads(line))
        except ValueError: pass
    return result


async def changes(mid, letter):
    mission = read(mid)
    workspace = run_path(mid, letter) / 'worktree'
    # Diff includes tracked edits; completed candidates also contain new files.
    output = await git(workspace, 'diff', '--no-ext-diff', '--stat', mission['baseline'])
    patch = await git(workspace, 'diff', '--no-ext-diff', '--no-textconv', mission['baseline'])
    return {'stat': scrub(output.decode(errors='replace'))[:20000], 'patch': scrub(patch.decode(errors='replace'))[:120000]}


async def integrate(mid, letter):
    async with _lock:
        mission = read(mid)
        if any(r['status'] in ACTIVE for r in mission['runs']): raise ValueError('Wait for both attempts to stop before choosing.')
        run = next((r for r in mission['runs'] if r['letter'] == letter), None)
        if not run or run['status'] != 'completed' or not run.get('commit'): raise ValueError('Choose a completed candidate.')
        if any(c['exit_code'] != 0 for c in run['checks']): raise ValueError('Candidate checks failed. Review the result before choosing.')
        if mission['integration']: return mission
        root = settings.project_root.resolve()
        # A changed HEAD needs an explicit new comparison; never silently overwrite.
        if (await git(root, 'rev-parse', 'HEAD')).decode().strip() != mission['head']:
            raise ValueError('The project HEAD changed. Start a new comparison against the current project.')
        _, current = await snapshot(root, folder(mid))
        if (await git(root, 'rev-parse', current + '^{tree}')) != (await git(root, 'rev-parse', mission['baseline'] + '^{tree}')):
            raise ValueError('Your working files changed during the comparison. Start a new comparison to preserve those edits.')
        branch = f'yapoc/integration/{mid}'
        workspace = folder(mid) / 'integration'
        await git(root, 'worktree', 'add', '-b', branch, str(workspace), run['commit'])
        result = {'letter': letter, 'branch': branch, 'status': 'checking', 'checks': []}
        mission.pop('runs'); mission['integration'] = result; write(folder(mid) / 'mission.json', mission)
        # Run the same check in the isolated integration worktree, not the live tree.
        from .checks import run_check_process
        _integrating.add(mid)
        try:
            check = await run_check_process(workspace, mission['check_command'])
            result.update(status='ready' if check['exit_code'] == 0 else 'checks_failed', checks=[check])
            write(folder(mid) / 'mission.json', mission)
            return read(mid)
        finally:
            _integrating.discard(mid)


async def shutdown():
    tasks = list(_jobs.values())
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    from .checks import stop_checks
    await stop_checks()
    from .preview import stop_previews
    await asyncio.to_thread(stop_previews)


def instance_parts(name: str):
    match = re.fullmatch(r'universe_([0-9a-f]{32})_([ab])', name)
    return match.groups() if match else None


def residents():
    from app.backend.models import AgentStatus
    result = []
    for mission in listing()[:1]:
        for run in mission['runs']:
            runtime = 'running' if run['status'] in ACTIVE else 'idle' if run['status'] == 'completed' else 'interrupted'
            result.append(AgentStatus(name=run['id'], office_role='builder', runtime_state=runtime,
                universe_id=mission['id'], universe_letter=run['letter'], status=runtime, model='Builder',
                has_task=run['status'] in ACTIVE, memory_entries=0, health_errors=0, process_state=runtime,
                state=runtime, task_summary=mission['objective'] + ' · ' + run['approach'], updated_at=run['updated_at'],
                input_tokens=run['input_tokens'], output_tokens=run['output_tokens']))
    return result


def open_preview(mid, letter):
    mission = read(mid)
    run_path(mid, letter)
    run = next(r for r in mission['runs'] if r['letter'] == letter)
    if run['status'] != 'completed': raise ValueError('Wait for a completed frontend build.')
    from .preview import start_preview
    root = preview_directory(run_path(mid, letter) / 'worktree')
    if root is None: raise ValueError('No isolated static preview was produced.')
    start_preview(f'{mid}-{letter}', root)
    return read(mid)


def preview_directory(workspace: Path):
    root = (workspace / 'app/frontend/dist').resolve()
    if not root.is_relative_to(workspace.resolve()) or not (root / 'index.html').is_file(): return None
    if not (root / 'index.html').resolve().is_relative_to(root): return None
    return root
