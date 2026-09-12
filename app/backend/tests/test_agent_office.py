"""Office presence must not inherit the legacy active-task fallback."""
import json
from unittest.mock import Mock
from app.backend import services


def test_dead_process_with_running_task_is_idle_in_office(tmp_path, monkeypatch):
    agent = tmp_path / 'builder_a'
    agent.mkdir()
    (agent / 'CONFIG.yaml').write_text('office_role: builder\n')
    (agent / 'STATUS.json').write_text(json.dumps({'state': 'running', 'pid': 123}))
    (agent / 'TASK.MD').write_text('---\nstatus: running\n---\n## Task\nBuild it\n')
    monkeypatch.setattr(services, 'BaseAgent', Mock(side_effect=RuntimeError('fixture')))
    monkeypatch.setattr(services, '_pid_alive', lambda _: False)
    result = services._build_agent_status(agent)
    assert result.office_role == 'builder'
    assert result.runtime_state == 'idle'
    assert result.pid is None


def test_live_instances_keep_separate_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(services, 'BaseAgent', Mock(side_effect=RuntimeError('fixture')))
    monkeypatch.setattr(services, '_pid_alive', lambda _: True)
    monkeypatch.setattr(services, '_is_stale_status', lambda _: False)
    results = []
    for name, state in [('builder_a', 'running'), ('builder_b', 'waiting')]:
        agent = tmp_path / name
        agent.mkdir()
        (agent / 'CONFIG.yaml').write_text('office_role: builder\n')
        (agent / 'STATUS.json').write_text(json.dumps({'state': state, 'pid': 123}))
        results.append(services._build_agent_status(agent))
    assert [r.name for r in results] == ['builder_a', 'builder_b']
    assert [r.office_role for r in results] == ['builder', 'builder']
    assert [r.runtime_state for r in results] == ['running', 'waiting']
