"""Bootstrap workspace scoping BEFORE importing any agent/backend modules."""
import asyncio
import json
from pathlib import Path
import sys

# Executed as a trusted host script, not from candidate code or its cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings


def main():
    mode = sys.argv[1]
    if mode == 'worker':
        control = Path(sys.argv[2]).resolve()
        request = json.loads((control / 'request.json').read_text())
        settings._execution_root = Path(request['workspace']).resolve()
        from app.backend.services.universes.worker import main as run_worker
        asyncio.run(run_worker(control))
    elif mode == 'check':
        root = Path(sys.argv[2]).resolve()
        settings._execution_root = root
        from app.backend.services.universes.checks import check
        print(json.dumps(asyncio.run(check(root, sys.argv[3])), separators=(',', ':')))
    else:
        raise ValueError('Unknown universe operation.')


if __name__ == '__main__':
    main()
