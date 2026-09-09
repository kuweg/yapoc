"""Blocking interprocess locks for local files on Unix and Windows."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def file_lock(path: Path):
    """Hold an exclusive lock on a stable sidecar file until context exit.

    Never truncate or unlink the lock file: other processes may be waiting on
    that same file. Windows locks byte zero, including beyond an empty EOF.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
