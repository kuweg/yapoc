"""Initialize the chosen writable folder, then run its own YAPOC code.

Only the clean release template enters the image. Existing installations are
preserved, including custom agents and self-modifications; setup is not update.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def seed(template: Path, root: Path) -> None:
    marker = root / ".yapoc-install.json"
    if not marker.exists():
        conflicts = [name for name in ("app", "data", ".env", "pyproject.toml", "poetry.lock") if (root / name).exists()]
        if conflicts:
            raise RuntimeError("Choose a folder without these reserved YAPOC paths: " + ", ".join(conflicts))
        marker.write_text(json.dumps({"format": 1, "state": "initializing"}) + "\n")
    state = json.loads(marker.read_text())
    if state.get("format") != 1:
        raise RuntimeError("Unsupported installation format; no files were changed.")
    if state.get("state") == "initializing":
        shutil.copytree(template / "app", root / "app", dirs_exist_ok=True)
        for name in ("pyproject.toml", "poetry.lock"):
            shutil.copy2(template / name, root / name)
        (root / "data").mkdir(exist_ok=True)
        # Writable HOME for unprivileged Linux UIDs and model caches.
        (root / ".cache").mkdir(exist_ok=True)
        marker.write_text(json.dumps({"format": 1, "state": "ready"}) + "\n")


def serve(root: Path) -> int:
    """Single process owner, including bounded shutdown and intentional restart."""
    stopping = False
    child = None

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    delay = 1
    while not stopping:
        started = time.monotonic()
        child = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.backend.main:app",
                                  "--host", "0.0.0.0", "--port", "8000"], cwd=root)
        (root / ".yapoc.pid").write_text(str(child.pid))
        while child.poll() is None and not stopping:
            time.sleep(0.2)
        if stopping:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            break
        # Successful graceful self-restart should not accumulate crash backoff.
        delay = 1 if child.returncode == 0 or time.monotonic() - started > 60 else min(delay * 2, 30)
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline and not stopping:
            time.sleep(0.2)
    return 0


def main() -> int:
    root = Path('/workspace')
    seed(Path('/opt/yapoc'), root)
    os.chdir(root)
    sys.path.insert(0, str(root))
    Path.home().mkdir(parents=True, exist_ok=True)
    if sys.argv[1:] == ['setup']:
        from app.cli.guided_setup import run_guided_setup
        return run_guided_setup()
    if sys.argv[1:] not in ([], ['serve']):
        raise RuntimeError("Expected setup or serve")
    if not (root / '.env').is_file():
        raise RuntimeError("Run guided setup before starting YAPOC")
    return serve(root)


if __name__ == '__main__':
    raise SystemExit(main())
