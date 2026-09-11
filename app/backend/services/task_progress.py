"""One presentation of queue progress for HTTP, websocket and dashboard clients.

Execution status describes a turn; progress also includes its asynchronous children.
"""
import json
from app.config import settings
from app.utils.db import get_queued_task


def metadata(row: dict) -> dict:
    try:
        value = json.loads(row.get('metadata') or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def progress(row: dict, seen: frozenset = frozenset()) -> dict:
    meta = metadata(row)
    state = {'pending': 'queued', 'error': 'failed', 'timeout': 'failed', 'done': 'completed'}.get(row['status'], row['status'])
    waiting = meta.get('abandoned_waits', [])
    waiting = waiting if isinstance(waiting, list) else []
    outcomes = meta.get('child_outcomes', {})
    outcomes = outcomes if isinstance(outcomes, dict) else {}
    deliveries = meta.get('child_deliveries', {})
    deliveries = deliveries if isinstance(deliveries, dict) else {}
    activity_at = meta.get('last_activity_at') or row.get('updated_at')
    activity = meta.get('last_activity', 'Task ' + state)
    references = meta.get('waiting_tasks', {})
    references = references if isinstance(references, dict) else {}
    if state == 'completed' and waiting:
        state = 'waiting'
        children = []
        for name in waiting:
            delivery = get_queued_task(deliveries.get(name, ''))
            if delivery and delivery['id'] not in seen and len(seen) < 20:
                child_progress = progress(delivery, seen | {row['id']})
                children.append(child_progress['state'])
                stamp = child_progress.get('last_activity_at')
                if stamp and (not activity_at or stamp > activity_at):
                    activity_at = stamp
                    activity = child_progress['last_activity']
            else:
                children.append('completed' if outcomes.get(name) in {'done', 'completed'} and not deliveries.get(name) else 'unknown')
                # Only read the explicitly recorded child run; agent names can
                # be reused later for a different conversation.
                if isinstance(name, str) and name.isidentifier() and references.get(name):
                    try:
                        from app.utils.frontmatter import parse_frontmatter
                        fields, _ = parse_frontmatter((settings.agents_dir / name / 'TASK.MD').read_text())
                        try:
                            status = json.loads((settings.agents_dir / name / 'STATUS.json').read_text())
                            if not isinstance(status, dict):
                                status = {}
                        except (OSError, ValueError):
                            status = {}
                        if fields.get('task_id') == references[name]:
                            child_state = fields.get('status', 'running')
                            if child_state in {'done', 'completed'}:
                                children[-1] = 'completed'
                            elif child_state in {'interrupted', 'error', 'blocked', 'failed', 'timeout', 'cancelled'}:
                                children[-1] = 'blocked'
                            elif child_state in {'running', 'pending'} and status.get('state') in {'running', 'starting', 'busy', 'waiting'}:
                                children[-1] = 'waiting'
                            stamp = status.get('updated_at')
                            if stamp and (not activity_at or stamp > activity_at):
                                activity_at = stamp
                                activity = f'{name}: {child_state}'
                    except (OSError, ValueError, TypeError):
                        pass
        if any(outcomes.get(name) in {'error', 'failed', 'interrupted', 'cancelled'} for name in waiting):
            state = 'blocked'
        elif all(value == 'completed' for value in children):
            state = 'completed'
        elif any(value in {'failed', 'blocked', 'interrupted', 'cancelled'} for value in children):
            state = 'blocked'
        elif any(value == 'unknown' for value in children):
            state = 'unknown'
    actions = {
        'unknown': 'This historical task has no current run or confirmed completion. Check its retained results in Tasks.',
        'queued': 'Waiting for an available agent.',
        'running': 'Working. You can continue the conversation.',
        'waiting': 'Delegated work continues; its result will return here.',
        'interrupted': 'Execution stopped. Review the checkpoint before retrying.',
        'blocked': 'Review the child result or recovery history before retrying.',
        'failed': 'Review the error and retained output before retrying.',
        'completed': 'Result available.', 'cancelled': 'Stopped by request.',
    }
    return {'state': state, 'waiting_on': waiting if state == 'waiting' else [],
            'last_activity_at': activity_at,
            'last_activity': activity,
            'next_action': actions.get(state, 'Review task details.'),
            'recovery_count': meta.get('recovery_count', 0)}


def present_task(row: dict) -> dict:
    activity = progress(row)
    result = {**row, 'progress': activity}
    if row.get('structured_result'):
        result['structured_result'] = {**row['structured_result'], 'progress': activity}
        if activity['state'] == 'waiting':
            result['structured_result']['status'] = 'partial'
    return result


def pending_handoff(task_id: str | None) -> list[str]:
    row = get_queued_task(task_id) if task_id else None
    names = metadata(row).get('abandoned_waits', []) if row else []
    return names if isinstance(names, list) else []
