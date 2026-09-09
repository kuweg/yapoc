"""Offline checks of persistent container workspace initialization."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    'yapoc_entrypoint', Path(__file__).resolve().parents[1] / 'docker/entrypoint.py'
)
entrypoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(entrypoint)


class DockerEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.template = Path(self.temp.name) / 'template'
        self.root = Path(self.temp.name) / 'workspace'
        (self.template / 'app').mkdir(parents=True)
        self.root.mkdir()
        (self.template / 'app/main.py').write_text('release')
        for name in ('pyproject.toml', 'poetry.lock'):
            (self.template / name).write_text('fixture')

    def test_seed_and_restart_preserve_user_code_and_credentials(self):
        entrypoint.seed(self.template, self.root)
        self.assertEqual((self.root / 'app/main.py').read_text(), 'release')
        self.assertTrue((self.root / 'data').is_dir())
        self.assertTrue((self.root / '.cache').is_dir())
        (self.root / 'app/main.py').write_text('customized')
        (self.root / '.env').write_text('PRIVATE=fixture')
        entrypoint.seed(self.template, self.root)
        self.assertEqual((self.root / 'app/main.py').read_text(), 'customized')
        self.assertEqual((self.root / '.env').read_text(), 'PRIVATE=fixture')

    def test_rejects_existing_unmanaged_workspace(self):
        (self.root / '.env').write_text('PRIVATE=fixture')
        with self.assertRaisesRegex(RuntimeError, 'reserved'):
            entrypoint.seed(self.template, self.root)
        self.assertFalse((self.root / 'app').exists())

    def test_resumes_interrupted_seed(self):
        (self.root / '.yapoc-install.json').write_text(
            json.dumps({'format': 1, 'state': 'initializing'})
        )
        entrypoint.seed(self.template, self.root)
        self.assertEqual(json.loads((self.root / '.yapoc-install.json').read_text())['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
