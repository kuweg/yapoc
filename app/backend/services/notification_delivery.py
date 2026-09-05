"""Durable handoff of child results to the master's normal task queue.

Notification storage is an outbox: creating a delivery does not consume its
input. Stable delivery IDs reconcile crashes on either side of the SQLite /
JSON boundary. Only a persisted successful result acknowledges that input.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.backend.services.notification_queue import notification_queue
from app.config import settings
from app.utils.db import create_queued_task, get_queued_task


def delivery_id(notification: dict) -> str:
    identity = [notification['parent_agent'], notification['child_agent'], notification.get('task_id')]
    if not identity[-1]:
        identity += [notification.get('session_id', ''), notification.get('completed_at'),
                     notification.get('status'), notification.get('result'), notification.get('error')]
    return 'notification-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def queue_pending_notifications() -> None:
    for notification in notification_queue.pending_entries('master'):
        base_id = delivery_id(notification)
        tid = base_id
        previous = None
        for attempt in range(1, settings.notification_max_attempts + 1):
            tid = base_id if attempt == 1 else f"{base_id}-retry-{attempt}"
            row = get_queued_task(tid)
            if not row:
                break
            if row['status'] in {'done', 'cancelled'}:
                notification_queue.acknowledge([notification])
                break
            if row['status'] not in {'error', 'timeout'}:
                break
            updated = datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00'))
            if (datetime.now(timezone.utc) - updated).total_seconds() < settings.notification_retry_seconds:
                break
            previous = row
        else:
            # Exhaustion stays visible as an error; the original outbox input
            # remains recoverable for an explicit operator retry.
            continue
        if row:
            continue
        planning = notification['child_agent'] == 'planning' and notification['status'] == 'done'
        instruction = (
            'Continue the original request. If this is an unexecuted plan, spawn the needed specialists '
            'and carry it through to completion. If already implemented, summarize the outcome. '
            if planning else 'Summarize this child result for the user. Do not re-spawn completed work. '
        )
        prompt = instruction + 'Do not restart the backend while processing this result.\n\n' + json.dumps(notification, ensure_ascii=False)
        # Recover the user's actual request, rather than treating a child plan
        # as independent authority to invent a new objective.
        sid = notification.get('session_id', '')
        original = get_queued_task(notification.get("parent_task_id", ""))
        if original:
            original_meta = json.loads(original.get("metadata") or "{}")
            prompt = 'Original user request:\n' + original_meta.get("original_prompt", original['prompt']) + '\n\n' + prompt
        if original and original["status"] == "cancelled":
            notification_queue.acknowledge([notification])
            continue
        if previous:
            prompt += ("\n\nA previous delivery attempt failed. Inspect existing child tasks and tool outcomes "
                       "before repeating any action; do not duplicate assignments. Previous partial output:\n"
                       + (previous.get("result") or "(outcome unknown)") + "\nError: " + (previous.get("error") or "unknown"))
        try:
            create_queued_task(id=tid, prompt=prompt, source='continuation' if planning else 'notification',
                               session_id=sid, metadata=json.dumps({'notification': notification, 'delivery_attempt': attempt}))
        except Exception:
            # Concurrent producer or crash recovery may already have inserted
            # this exact delivery. Never acknowledge an unpersisted handoff.
            if not get_queued_task(tid):
                raise
