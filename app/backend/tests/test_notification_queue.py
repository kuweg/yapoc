import importlib.util
from pathlib import Path


def _load_notification_queue_class():
    module_path = Path(__file__).resolve().parents[1] / "services" / "notification_queue.py"
    spec = importlib.util.spec_from_file_location("notification_queue_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NotificationQueue


NotificationQueue = _load_notification_queue_class()


def test_session_scoped_drain_only_consumes_matching_session(tmp_path: Path):
    q = NotificationQueue(path=tmp_path / "notification_queue.json")

    q.enqueue(
        parent_agent="master",
        child_agent="builder",
        status="done",
        result="A",
        session_id="sess-a",
    )
    q.enqueue(
        parent_agent="master",
        child_agent="keeper",
        status="done",
        result="B",
        session_id="sess-b",
    )

    drained_a = q.drain("master", session_id="sess-a")
    assert len(drained_a) == 1
    assert drained_a[0]["child_agent"] == "builder"

    # Session B remains pending after draining only session A.
    assert q.pending_count("master", session_id="sess-b") == 1


def test_pending_sessions_reports_distinct_session_ids(tmp_path: Path):
    q = NotificationQueue(path=tmp_path / "notification_queue.json")

    q.enqueue("master", "builder", "done", result="x", session_id="sess-1")
    q.enqueue("master", "keeper", "done", result="y", session_id="sess-1")
    q.enqueue("master", "planning", "error", error="boom", session_id="sess-2")

    sessions = q.pending_sessions("master")
    assert sessions == ["sess-1", "sess-2"]


def test_dedup_includes_session_id(tmp_path: Path):
    q = NotificationQueue(path=tmp_path / "notification_queue.json")

    # Same payload, different session IDs must be kept as separate notifications.
    q.enqueue("master", "builder", "done", result="ok", session_id="sess-a")
    q.enqueue("master", "builder", "done", result="ok", session_id="sess-b")

    assert q.pending_count("master") == 2
