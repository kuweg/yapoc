"""A backend launched by the short-lived CLI must survive its terminal."""
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock


def test_backend_start_is_detached(tmp_path, monkeypatch):
    import app.cli.main as cli
    monkeypatch.setattr(cli, '_read_pid', lambda: None)
    monkeypatch.setattr(cli, '_pids_listening_on', lambda _: [])
    monkeypatch.setattr(cli, '_SERVER_OUTPUT', tmp_path / 'server.log')
    monkeypatch.setattr(cli, '_SERVER_CRASH', tmp_path / 'crash.log')
    monkeypatch.setattr(cli, '_write_pid', lambda _: None)
    monkeypatch.setattr(cli, 'server_exit_watcher', lambda *args: None)
    spawn = Mock(return_value=SimpleNamespace(pid=1234))
    monkeypatch.setattr(cli.subprocess, 'Popen', spawn)
    cli._do_start()
    assert spawn.call_args.kwargs['start_new_session'] is True
    assert spawn.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert '--timeout-graceful-shutdown' in spawn.call_args.args[0]
    spawn.call_args.kwargs['stdout'].close()
