import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.backend.services import universes as u
from app.backend.routers.universes import Launch


@pytest.fixture
async def repository(tmp_path, monkeypatch):
    monkeypatch.setattr(u, 'settings', SimpleNamespace(project_root=tmp_path))
    await u.git(tmp_path, 'init')
    (tmp_path / 'code.txt').write_text('original\n')
    (tmp_path / '.gitignore').write_text('data/\n.env\n')
    await u.git(tmp_path, 'add', '.')
    await u.git(tmp_path, 'commit', '-m', 'base')
    yield tmp_path
    await u.shutdown()


async def test_snapshot_includes_dirty_files_without_touching_index_or_secrets(repository):
    root = repository
    (root / 'code.txt').write_text('user edit\n')
    (root / 'new.txt').write_text('new\n')
    (root / '.env').write_text('PRIVATE_TOKEN=must-not-copy')
    (root / 'credentials.json').write_text('must-not-copy')
    (root / 'data').mkdir()
    (root / 'data/private').write_text('must-not-copy')
    before = await u.git(root, 'status', '--porcelain')
    index_before = (root / '.git/index').read_bytes()
    folder = root / 'data/snapshot'; folder.mkdir()
    head, baseline = await u.snapshot(root, folder)
    assert before == await u.git(root, 'status', '--porcelain')
    assert index_before == (root / '.git/index').read_bytes()
    assert head != baseline
    files = (await u.git(root, 'ls-tree', '-r', '--name-only', baseline)).decode()
    assert 'new.txt' in files and 'credentials.json' not in files and '.env' not in files and 'data/' not in files
    assert await u.git(root, 'show', baseline + ':code.txt') == b'user edit\n'


async def setup_pair(repository, monkeypatch):
    from app.utils.adapters.models import ALL_PRICING
    monkeypatch.setattr('app.utils.agent_settings.resolve_agent', lambda _: {'adapter': 'openai', 'model': next(iter(ALL_PRICING)), 'temperature': 0, 'max_tokens': 100})
    monkeypatch.setattr('app.utils.tools.process_sandbox.command', lambda *a, **k: ['fixture'])
    async def fake_execute(mid, letter):
        control = u.run_path(mid, letter)
        (control / 'worktree/code.txt').write_text(letter + '\n')
        u.state_update(mid, letter, status='completed', checks=[{'command':'fixture','exit_code':0,'output':'ok'}])
        await u.finish_run(mid, letter)
        u._jobs.pop(f'{mid}-{letter}', None)
    monkeypatch.setattr(u, 'execute', fake_execute)
    monkeypatch.setattr('app.backend.services.universes.preview.start_preview', lambda *a: None)
    request = Launch(objective='Change the code', approaches=['Approach A', 'Approach B'], session_id='test', check_command='python --version')
    mission = await u.create(request)
    await asyncio.gather(*list(u._jobs.values()))
    return u.read(mission['id'])


async def test_independent_worktrees_and_choose_preserves_live_tree(repository, monkeypatch):
    before = await u.git(repository, 'status', '--porcelain')
    mission = await setup_pair(repository, monkeypatch)
    mid = mission['id']
    assert (u.run_path(mid,'a')/'worktree/code.txt').read_text() == 'a\n'
    assert (u.run_path(mid,'b')/'worktree/code.txt').read_text() == 'b\n'
    assert (repository/'code.txt').read_text() == 'original\n'
    assert before == await u.git(repository, 'status', '--porcelain')
    monkeypatch.setattr('app.backend.services.universes.checks.run_check_process', AsyncMock(return_value={'command':'fixture','exit_code':0,'output':'ok'}))
    chosen = await u.integrate(mid, 'a')
    assert chosen['integration']['status'] == 'ready'
    assert (u.folder(mid)/'integration/code.txt').read_text() == 'a\n'
    assert (repository/'code.txt').read_text() == 'original\n'
    assert (await u.git(repository,'branch','--show-current')).decode().strip() != chosen['integration']['branch']
    assert (await u.integrate(mid,'a'))['integration'] == chosen['integration']


async def test_changed_workspace_blocks_integration(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    (repository/'code.txt').write_text('new concurrent edit\n')
    with pytest.raises(ValueError, match='working files changed'):
        await u.integrate(mission['id'],'a')
    assert (repository/'code.txt').read_text() == 'new concurrent edit\n'


async def test_failed_checks_cannot_be_selected(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    u.state_update(mission['id'],'a',checks=[{'exit_code':1}])
    with pytest.raises(ValueError, match='checks failed'): await u.integrate(mission['id'],'a')


async def test_stale_run_is_interrupted_and_history_is_session_scoped(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    u.state_update(mission['id'],'a',status='running')
    assert u.read(mission['id'])['runs'][0]['status'] == 'interrupted'
    assert len(u.listing('test')) == 1 and u.listing('other') == []


def test_request_validation_and_path_traversal():
    with pytest.raises(ValueError): u.folder('../outside')
    with pytest.raises(ValueError): u.run_path('a'*32,'../outside')
    with pytest.raises(ValueError): Launch(objective='task', approaches=['a','b'],session_id='x',check_command='npm run build; rm -rf /')
    with pytest.raises(ValueError): Launch(objective='task', approaches=['a'],session_id='x')


async def test_cancel_only_target_run(repository):
    # Cancellation handles are run-scoped and never target the ordinary builder.
    async def wait(): await asyncio.Event().wait()
    first, second = asyncio.create_task(wait()), asyncio.create_task(wait())
    u._jobs['a'*32+'-a'], u._jobs['a'*32+'-b'] = first, second
    await asyncio.sleep(0)
    first.cancel(); await asyncio.gather(first, return_exceptions=True)
    assert not second.done()
    second.cancel(); await asyncio.gather(second, return_exceptions=True)
    u._jobs.clear()


async def test_worker_uses_existing_tool_loop_without_touching_host(tmp_path, monkeypatch):
    from app.config import settings
    from app.backend.services.universes import worker
    from app.utils.adapters import ToolCall, TurnComplete, TextDelta
    monkeypatch.setattr(settings, '_execution_root', None)
    monkeypatch.setattr(settings, 'budget_per_task_usd', 10)
    monkeypatch.setattr(settings, 'git_autocheckpoint_enabled', False)
    monkeypatch.setattr(settings, 'github_enabled', False)
    root = tmp_path / 'workspace'; root.mkdir()
    control = tmp_path / 'control'; control.mkdir()
    request = {'id':'a'*32,'letter':'a','workspace':str(root),'minutes':1,'budget_usd':1,
               'objective':'Create hello.txt','approach':'small','requirements':'plain text','check_command':'python --version',
               'config':{'adapter':'openai','model':'gpt-4o-mini','max_tokens':100,'temperature':0}}
    u.write(control/'request.json', request)
    u.write(control/'state.json', {'id':'universe_'+'a'*32+'_a','status':'preparing','cost_usd':0,'input_tokens':0,'output_tokens':0})
    seen = []
    class Adapter:
        def context_window_size(self): return 100000
        async def stream_with_tools(self, **kwargs):
            seen.append({tool.name for tool in kwargs['tools']})
            if len(seen) == 1:
                yield TurnComplete(stop_reason='tool_use', tool_calls=[ToolCall('write','file_write',{'path':'hello.txt','content':'hello'})], assistant_content=[{'type':'tool_use','id':'write','name':'file_write','input':{'path':'hello.txt','content':'hello'}}])
            else:
                yield TextDelta('Finished')
                yield TurnComplete(stop_reason='end_turn', assistant_content=[{'type':'text','text':'Finished'}])
    monkeypatch.setattr('app.utils.adapters.get_adapter', lambda _: Adapter())
    monkeypatch.setattr('app.utils.tools.security_gate.classify', AsyncMock(return_value=('allow','fixture')))
    monkeypatch.setattr('app.backend.services.universes.checks.check', AsyncMock(return_value={'command':'fixture','exit_code':0,'output':'ok'}))
    await worker.main(control)
    state = json.loads((control/'state.json').read_text())
    assert state['status'] == 'completed', state
    assert (root/'hello.txt').read_text() == 'hello'
    assert seen and all(names == {'file_read','file_list','file_write','file_edit','shell_exec'} for names in seen)
    assert not (tmp_path/'hello.txt').exists()


async def test_preview_denies_directory_and_symlink_escape(tmp_path):
    import urllib.request
    from app.backend.services.universes import preview
    root = tmp_path/'dist'; root.mkdir()
    (root/'index.html').write_text('preview')
    (root/'.env').write_text('secret')
    outside=tmp_path/'private.txt'; outside.write_text('secret')
    (root/'leak.txt').symlink_to(outside)
    (root/'folder').mkdir(); (root/'folder/index.html').symlink_to(outside)
    url=preview.start_preview('fixture',root)
    try:
        with urllib.request.urlopen(url) as response: assert response.read() == b'preview'
        for suffix in ('/.env','/leak.txt','/folder/'):
            with pytest.raises(urllib.error.HTTPError) as caught: urllib.request.urlopen(url+suffix)
            assert caught.value.code == 404
    finally: preview.stop_previews()


async def test_preview_can_be_reopened_after_restart_and_rejects_root_symlink(repository, monkeypatch):
    from app.backend.services.universes import preview
    original_start = preview.start_preview
    mission = await setup_pair(repository, monkeypatch)
    monkeypatch.setattr(preview, 'start_preview', original_start)
    mid=mission['id']; workspace=u.run_path(mid,'a')/'worktree'
    dist=workspace/'app/frontend/dist'; dist.mkdir(parents=True)
    (dist/'index.html').write_text('safe preview')
    assert u.read(mid)['runs'][0]['preview_url'] is None
    assert u.open_preview(mid,'a')['runs'][0]['preview_url']
    preview.stop_previews()
    assert u.read(mid)['runs'][0]['preview_url'] is None
    assert u.open_preview(mid,'a')['runs'][0]['preview_url']
    preview.stop_previews()
    (dist/'index.html').unlink(); dist.rmdir()
    outside=repository/'outside'; outside.mkdir(); (outside/'index.html').write_text('private')
    dist.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='isolated static preview'): u.open_preview(mid,'a')


async def test_stop_api_keeps_other_universe_running(repository, monkeypatch):
    mission=await setup_pair(repository, monkeypatch)
    mid=mission['id']
    async def wait(): await asyncio.Event().wait()
    first=asyncio.create_task(wait()); second=asyncio.create_task(wait())
    u._jobs[f'{mid}-a']=first; u._jobs[f'{mid}-b']=second
    await u.stop(mid,'a')
    assert first.cancelled() and not second.done()
    await u.stop(mid)
    assert second.cancelled()
    u._jobs.clear()


async def test_discard_stops_runs_and_cleanup_preserves_project(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    mid = mission['id']
    before = await u.git(repository, 'status', '--porcelain')
    async def wait(): await asyncio.Event().wait()
    tasks = [asyncio.create_task(wait()) for _ in range(2)]
    for letter, task in zip(('a', 'b'), tasks): u._jobs[f'{mid}-{letter}'] = task
    with pytest.raises(ValueError, match='Discard both'): await u.cleanup(mid)
    discarded = await u.discard(mid)
    assert discarded['discarded_at'] and all(task.cancelled() for task in tasks)
    assert not u.residents()
    assert (u.run_path(mid, 'a') / 'worktree/code.txt').exists()
    with pytest.raises(ValueError, match='discarded'): await u.integrate(mid, 'a')
    assert (await u.cleanup(mid))['deleted']
    assert not u.folder(mid).exists() and not u.listing()
    assert mid not in (await u.git(repository, 'branch')).decode()
    assert mid not in (await u.git(repository, 'worktree', 'list')).decode()
    assert before == await u.git(repository, 'status', '--porcelain')
    assert (repository / 'code.txt').read_text() == 'original\n'
    u._jobs.clear()


async def test_discard_preserves_chosen_integration(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    monkeypatch.setattr('app.backend.services.universes.checks.run_check_process', AsyncMock(return_value={'command':'fixture','exit_code':0,'output':'ok'}))
    await u.integrate(mission['id'], 'a')
    with pytest.raises(ValueError, match='integration branch'): await u.discard(mission['id'])
    with pytest.raises(ValueError): await u.cleanup(mission['id'])
    assert (u.folder(mission['id']) / 'integration/code.txt').exists()


async def test_cleanup_refuses_candidate_checked_out_elsewhere(repository, monkeypatch):
    mission = await setup_pair(repository, monkeypatch)
    mid = mission['id']
    await u.discard(mid)
    moved = repository / 'retained-worktree'
    await u.git(repository, 'worktree', 'move', str(u.run_path(mid, 'a') / 'worktree'), str(moved))
    with pytest.raises(ValueError, match='outside this comparison'): await u.cleanup(mid)
    assert (moved / 'code.txt').exists()
    assert (u.run_path(mid, 'b') / 'worktree/code.txt').exists()
