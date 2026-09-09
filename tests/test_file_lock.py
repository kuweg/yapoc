"""Run with unittest as well as pytest; requires only the standard library."""
import multiprocessing
import importlib.util
from pathlib import Path
import tempfile
import unittest

# Load the standalone helper without app.utils' settings/dependency imports.
_spec = importlib.util.spec_from_file_location(
    'yapoc_file_lock', Path(__file__).resolve().parents[1] / 'app/utils/file_lock.py'
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
file_lock = _module.file_lock


def _increment(counter, ready):
    ready.wait(10)
    path = Path(counter)
    for _ in range(40):
        with file_lock(path.with_suffix('.lock')):
            value = int(path.read_text())
            path.write_text(str(value + 1))


class FileLockTests(unittest.TestCase):
    def test_concurrent_processes_do_not_lose_writes(self):
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as folder:
            counter = Path(folder) / 'counter'
            counter.write_text('0')
            ready = ctx.Event()
            workers = [ctx.Process(target=_increment, args=(str(counter), ready)) for _ in range(4)]
            try:
                for worker in workers:
                    worker.start()
                ready.set()
                for worker in workers:
                    worker.join(30)
                    self.assertEqual(worker.exitcode, 0)
                self.assertEqual(counter.read_text(), '160')
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join()

    def test_exception_releases_lock_without_truncating_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.lock'
            path.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                with file_lock(path):
                    raise ValueError('test')
            with file_lock(path):
                self.assertEqual(path.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
