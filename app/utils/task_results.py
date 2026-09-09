"""Versioned task outcomes assembled from runtime evidence, never model JSON."""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field


class Verification(BaseModel):
    command: str
    status: Literal['passed', 'failed', 'unknown']
    exit_code: int | None = None
    evidence_event_seq: int
    evidence_url: str


class ResultArtifact(BaseModel):
    id: str
    type: str
    name: str
    url: str


class ResultUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    scope: str = 'Direct task stream; excludes delegated agents'


class StructuredResult(BaseModel):
    schema_version: Literal[1] = 1
    task_id: str
    status: Literal['succeeded', 'partial', 'failed', 'blocked', 'cancelled']
    summary: str
    changes: dict[str, list[str]] = Field(default_factory=lambda: {'files': []})
    verification_status: Literal['checks_passed', 'failed', 'unknown', 'not_run'] = 'not_run'
    verification: list[Verification] = Field(default_factory=list)
    artifacts: list[ResultArtifact] = Field(default_factory=list)
    usage: ResultUsage = Field(default_factory=ResultUsage)
    limitations: list[str] = Field(default_factory=list)


def build_result(task_id: str, state: str, text: str, error: str, events: list[dict], artifacts: list[dict] | tuple = ()) -> StructuredResult:
    status = {'done': 'succeeded', 'completed': 'succeeded', 'partial': 'partial', 'blocked': 'blocked', 'cancelled': 'cancelled'}.get(state, 'failed')
    if state in {'timeout', 'error', 'failed'} and text.strip():
        status = 'partial'
    result = StructuredResult(task_id=task_id, status=status, summary=(text.strip() or error.strip() or f'Task {status}.')[:2000])
    pending = defaultdict(deque)
    paths = set()
    for event in events:
        kind = event.get('type')
        if kind == 'usage_stats':
            for field in ['input_tokens', 'output_tokens']:
                count = event.get(field)
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    setattr(result.usage, field, (getattr(result.usage, field) or 0) + count)
        elif kind == 'tool_start':
            pending[event.get('name')].append(event.get('input') if isinstance(event.get('input'), dict) else {})
        elif kind == 'tool_done':
            name = event.get('name')
            if not pending[name]:
                continue
            args = pending[name].popleft()
            output = str(event.get('result', ''))
            failed = bool(event.get('is_error')) or output.startswith('ERROR:')
            if name in {'file_write', 'file_edit', 'file_delete'} and not failed:
                path = args.get('path')
                if isinstance(path, str):
                    paths.add(path)
            if name == 'shell_exec':
                # shell_exec itself appends this final line after communicate().
                match = re.search(r'(?:^|\n)Exit code: (-?\d+)\s*\Z', output)
                code = int(match[1]) if match else None
                seq = event['seq']
                result.verification.append(Verification(command=str(args.get('command', '')), exit_code=code,
                    status='failed' if failed or (code is not None and code != 0) else 'passed' if code == 0 else 'unknown',
                    evidence_event_seq=seq, evidence_url=f'/api/tasks/{quote(task_id, safe="")}/evidence/{seq}'))
    result.changes['files'] = sorted(paths)
    if result.verification:
        states = {v.status for v in result.verification}
        result.verification_status = 'failed' if 'failed' in states else 'unknown' if 'unknown' in states else 'checks_passed'
    for artifact in artifacts:
        # Only durable registry records explicitly owned by this task qualify.
        if artifact.get('source_task') == task_id and artifact.get('id'):
            aid = str(artifact['id'])
            result.artifacts.append(ResultArtifact(id=aid, type=str(artifact.get('kind', 'file')),
                name=str(artifact.get('name', aid)), url=f'/api/artifacts/{quote(aid, safe="")}/download'))
    result.limitations.append('Command exit codes record execution, not proof that the task objective was met.')
    result.limitations.append('File changes cover successful file tools only; shell and delegated edits are not inferred.')
    if not events:
        result.limitations.append('No runtime evidence was recorded for this task.')
    if error:
        result.limitations.append(error[:2000])
    return result


def save_result(db, key: str, task_id: str, state: str, text: str = '', error: str = '') -> None:
    events = []
    for row in db.execute('SELECT seq, payload FROM task_events WHERE task_id=? ORDER BY seq', (task_id,)):
        try:
            events.append({**json.loads(row['payload']), 'seq': row['seq']})
        except (TypeError, json.JSONDecodeError):
            continue
    from app.backend.services.artifacts import list_artifacts
    artifact_error = False
    try:
        artifacts = list_artifacts(task=task_id) if task_id else []
    except (OSError, ValueError, TypeError):
        artifacts = []
        artifact_error = True
    result = build_result(task_id or key, state, text or '', error or '', events, artifacts)
    if artifact_error:
        result.limitations.append('Artifact registry unavailable when this result was recorded.')
    db.execute('INSERT INTO task_results (result_key, payload) VALUES (?, ?) ON CONFLICT(result_key) DO UPDATE SET payload=excluded.payload',
               (key, result.model_dump_json()))


def attach_result(db, row, key: str) -> dict:
    task = dict(row)
    saved = db.execute('SELECT payload FROM task_results WHERE result_key=?', (key,)).fetchone()
    task['structured_result'] = json.loads(saved['payload']) if saved else None
    return task
