"""Non-secret process identity to detect workers running an older checkout."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]


def code_revision() -> str:
    digest = hashlib.sha256()
    for relative in ('app/config/settings.py', 'app/agents/base/runner.py',
                     'app/agents/base/__init__.py', 'app/backend/dispatcher.py',
                     'app/backend/main.py', 'app/utils/tools/process_sandbox.py',
                     'app/utils/tools/delegation.py', 'app/backend/services/task_progress.py',
                     'app/backend/services/recovery.py'):
        path = ROOT / relative
        digest.update(relative.encode())
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


PROCESS_IDENTITY = {'boot_id': uuid.uuid4().hex, 'pid': os.getpid(),
                    'started_at': datetime.now(timezone.utc).isoformat(),
                    'revision': code_revision()}
