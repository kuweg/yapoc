"""Bounded, idempotent restart recovery with retained evidence and original IDs."""
import json
from datetime import datetime, timezone
from app.config import settings
from app.utils.db import get_tasks_by_status, get_queued_task, update_queued_task
from .task_progress import metadata


def has_live_child(task_id: str) -> bool:
    import psutil
    from app.utils.frontmatter import parse_frontmatter
    for path in settings.agents_dir.glob('*/TASK.MD'):
        try:
            fields, _ = parse_frontmatter(path.read_text())
            if fields.get('parent_task_id') != task_id or fields.get('status') not in {'pending', 'running'}:
                continue
            status = json.loads(path.with_name('STATUS.json').read_text())
            pid = status.get('pid')
            if not isinstance(pid, int):
                continue
            proc = psutil.Process(pid)
            args = proc.cmdline()
            if ('app.agents.base.runner_entry' in args and '--agent' in args
                    and args[args.index('--agent') + 1] == path.parent.name
                    and proc.cwd() == str(settings.project_root)):
                return True
        except (OSError, ValueError, IndexError, psutil.Error):
            continue
    return False


def recover_interrupted_tasks(task_id: str | None = None, *, manual: bool = False) -> list[str]:
    from app.utils.conversation_store import load
    from .task_runtime import append_event
    recovered = []
    tasks = [get_queued_task(task_id)] if task_id else get_tasks_by_status('running', 'interrupted', limit=10000)
    for task in tasks:
        if not task or task['status'] not in ({'interrupted', 'blocked', 'error', 'timeout', 'failed', 'done'} if manual else {'running', 'interrupted'}):
            continue
        if task['status'] == 'done':
            from .task_progress import progress
            if progress(task)['state'] != 'blocked':
                continue
        meta = metadata(task)
        if has_live_child(task['id']):
            update_queued_task(task['id'], status='blocked', error='A worker from this run is still alive. Inspect its status before resuming.')
            continue
        try:
            count = int(meta.get('recovery_count', 0))
        except (TypeError, ValueError):
            count = 0
        now = datetime.now(timezone.utc).isoformat()
        meta.setdefault('original_prompt', task['prompt'])
        meta['last_interruption_at'] = now
        history = meta.get('recovery_history', [])
        history = history if isinstance(history, list) else []
        meta['recovery_history'] = [*history[-19:], {'at': now, 'previous_status': task['status']}]
        if not manual and count >= settings.restart_recovery_limit:
            update_queued_task(task['id'], status='blocked', error='Automatic restart recovery limit reached. Review retained output before retrying.', metadata=json.dumps(meta))
            continue
        try:
            checkpoint = load('run-' + task['id']) or ''
        except (OSError, ValueError):
            checkpoint = ''
        # Bound model context; full evidence remains in the durable event store.
        checkpoint = checkpoint[-24000:]
        previous = {key: meta.pop(key) for key in ('abandoned_waits', 'waiting_tasks', 'child_deliveries', 'child_outcomes') if key in meta}
        if previous:
            meta['recovery_history'][-1]['delegation'] = previous
        meta.update(recovery_count=count + 1, last_activity_at=now,
                    last_activity='Recovered after backend restart')
        meta.pop('history', None)
        prompt = (
            '[Recover interrupted run] Continue the original request. The previous process stopped. '
            'A tool without a recorded result has an UNKNOWN outcome. Inspect durable events, files, '
            'child assignments and external state before repeating side effects. Do not duplicate work.\n\n'
            + str(meta['original_prompt']) + '\n\nWorking checkpoint:\n'
            + (checkpoint or 'No transcript checkpoint. Inspect durable events and child assignments first.')
        )
        update_queued_task(task['id'], status='pending', prompt=prompt, metadata=json.dumps(meta),
                           started_at=None, assigned_agent=None, completed_at=None, error=None)
        append_event(task['id'], {'type': 'status', 'state': 'queued', 'text': 'Recovered after backend restart', 'timestamp': now})
        recovered.append(task['id'])
    return recovered
