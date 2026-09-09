"""Durable registry for generated artifacts and their version lineage."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings

_lock = threading.Lock()


def _project_root() -> Path:
    """Project root, isolated for tests without mutating Settings properties."""
    return settings.project_root


def _root() -> Path:
    return _project_root() / "data" / "artifacts"


def _index_path() -> Path:
    return _root() / "artifacts.json"


def _generated_root() -> Path:
    return (_project_root() / "data" / "generated").resolve()


def _load_index() -> dict[str, dict[str, Any]]:
    path = _index_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        backup = path.with_suffix(".json.bak")
        if backup.exists():
            try:
                return json.loads(backup.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}


def _save_index(index: dict[str, dict[str, Any]]) -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = _index_path()
    if path.exists():
        try:
            path.replace(path.with_suffix(".json.bak"))
        except OSError:
            pass
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(index, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _classify_path(path: Path) -> str:
    from app.backend.routers.files import _classify
    return _classify(path)


def _media_type_for(path: Path) -> str:
    from app.backend.routers.files import _media_type
    return _media_type(path)


def _validated_path(path: str | Path) -> tuple[Path, str]:
    candidate = Path(path)
    absolute = candidate.resolve() if candidate.is_absolute() else (_project_root() / candidate).resolve()
    generated = _generated_root()
    if not absolute.is_relative_to(generated):
        raise ValueError("Artifact path must be a file under data/generated")
    if not absolute.is_file():
        raise ValueError("Artifact path must be an existing file")
    return absolute, str(absolute.relative_to(_project_root().resolve()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_artifact(
    path: str | Path,
    source_agent: str = "generated",
    source_task: Optional[str] = None,
    source_session: Optional[str] = None,
    parent_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Register a generated file, creating or extending its stem-based lineage."""
    absolute, relative = _validated_path(path)
    now = datetime.now(timezone.utc).isoformat()
    name = absolute.name
    stem = absolute.stem
    size = absolute.stat().st_size
    checksum = _sha256(absolute)
    kind = _classify_path(absolute)
    mime = _media_type_for(absolute)
    version_entry = {
        "version": 1,
        "path": relative,
        "sha256": checksum,
        "size": size,
        "created_at": now,
        "source_agent": source_agent,
        "source_task": source_task,
        "source_session": source_session,
        "parent_id": parent_id,
    }

    with _lock:
        index = _load_index()
        existing = next((record for record in index.values() if record.get("stem") == stem), None)
        if existing:
            version = int(existing.get("version", 0)) + 1
            version_entry["version"] = version
            existing["name"] = name
            existing["path"] = relative
            existing["kind"] = kind
            existing["mime"] = mime
            existing["size"] = size
            existing["sha256"] = checksum
            existing["updated_at"] = now
            existing["source_agent"] = source_agent
            existing["source_task"] = source_task
            existing["source_session"] = source_session
            existing["version"] = version
            if parent_id is not None:
                existing["parent_id"] = parent_id
            existing.setdefault("versions", []).append(version_entry)
            if metadata is not None:
                existing["metadata"] = metadata
            _save_index(index)
            return dict(existing)

        artifact_id = uuid.uuid4().hex
        record = {
            "id": artifact_id,
            "name": name,
            "stem": stem,
            "path": relative,
            "kind": kind,
            "mime": mime,
            "size": size,
            "sha256": checksum,
            "created_at": now,
            "updated_at": now,
            "source_agent": source_agent,
            "source_task": source_task,
            "source_session": source_session,
            "version": 1,
            "parent_id": parent_id,
            "versions": [version_entry],
            "metadata": metadata or {},
        }
        index[artifact_id] = record
        _save_index(index)
        return dict(record)


def resolve_provenance(
    agent_dir: Optional[Path] = None,
    session_id: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """Work out (agent, task_id, session_id) for an artifact being created now.

    Two execution shapes have to be covered, which is why this is a chain
    rather than a single lookup:

    * In-process (master, and anything running under the backend dispatcher)
      the task id is on the ``current_task_id`` ContextVar.
    * Sub-process agents (``runner_entry.py``) have no ContextVar — the
      dispatcher that set it lives in another process. Their task id is in
      TASK.MD frontmatter, which the runner writes.

    Everything is best-effort: an artifact registered with partial provenance
    beats one registered with none, and beats a tool crashing over metadata.
    """
    agent = agent_dir.name if agent_dir is not None else "generated"
    task_id: Optional[str] = None
    session: Optional[str] = session_id or None

    try:
        from app.backend.services.task_runtime import current_task_id
        task_id = current_task_id.get() or None
    except Exception:
        task_id = None

    if (task_id is None or session is None) and agent_dir is not None:
        try:
            from app.utils.frontmatter import parse_frontmatter_fields
            fields = parse_frontmatter_fields((agent_dir / "TASK.MD").read_text(encoding="utf-8"))
            task_id = task_id or (fields.get("task_id") or None)
            session = session or (fields.get("session_id") or None)
        except Exception:
            pass

    return agent, task_id, session


def register_generated(
    path: str | Path,
    agent_dir: Optional[Path] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Register a file a tool just produced, with provenance filled in.

    This is the entry point every generating tool should use. Registering at
    creation is the only moment the producing task is knowable — the
    ``backfill_scan`` fallback that used to be the sole path can see the file
    but not who made it, which is why every pre-existing record reads
    ``source_agent: backfill`` with a null task.

    Returns the record, or ``None`` if registration failed. Never raises: a
    tool that produced a perfectly good chart must not report failure because
    the bookkeeping around it broke.
    """
    try:
        agent, task_id, session = resolve_provenance(agent_dir, session_id)
        return register_artifact(
            path,
            source_agent=agent,
            source_task=task_id,
            source_session=session,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - bookkeeping must never fail the tool
        import logging
        logging.getLogger(__name__).warning(
            "artifacts: could not register %s", path, exc_info=True
        )
        return None


def backfill_scan() -> int:
    generated = _generated_root()
    if not generated.exists():
        return 0
    with _lock:
        known_stems = {record.get("stem") for record in _load_index().values()}
    added = 0
    for path in generated.iterdir():
        if path.is_file() and not path.name.startswith(".") and path.stem not in known_stems:
            register_artifact(path, source_agent="backfill")
            known_stems.add(path.stem)
            added += 1
    return added


def list_artifacts(
    source_agent: Optional[str] = None,
    kind: Optional[str] = None,
    session: Optional[str] = None,
    task: Optional[str] = None,
) -> list[dict[str, Any]]:
    backfill_scan()
    with _lock:
        records = [dict(record) for record in _load_index().values()]
    if source_agent is not None:
        records = [record for record in records if record.get("source_agent") == source_agent]
    if kind is not None:
        records = [record for record in records if record.get("kind") == kind]
    if session is not None:
        records = [record for record in records if record.get("source_session") == session]
    if task is not None:
        records = [record for record in records if record.get("source_task") == task]
    return sorted(records, key=lambda record: record.get("updated_at", ""), reverse=True)


def get_artifact(artifact_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        record = _load_index().get(artifact_id)
        return dict(record) if record else None


def link_artifact_to_source(
    artifact_id: str,
    source_file_id: str,
    source_file_name: str,
) -> Optional[dict[str, Any]]:
    """Attach stable upload-source metadata to an existing artifact."""
    with _lock:
        index = _load_index()
        record = index.get(artifact_id)
        if not record:
            return None
        metadata = dict(record.get("metadata") or {})
        metadata["source_file_id"] = source_file_id
        metadata["source_file_name"] = source_file_name
        record["metadata"] = metadata
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        index[artifact_id] = record
        _save_index(index)
        return dict(record)


def get_versions(artifact_id: str) -> list[dict[str, Any]]:
    record = get_artifact(artifact_id)
    return list(record.get("versions", [])) if record else []


def delete_artifact(artifact_id: str) -> bool:
    """Remove an artifact record and its underlying generated file (if any).

    Index removal is the source of truth; file unlink failures are ignored.
    Returns True if the record existed and was removed, False otherwise.
    """
    with _lock:
        index = _load_index()
        record = index.get(artifact_id)
        if not record:
            return False
        del index[artifact_id]
        _save_index(index)

    relative = record.get("path")
    if relative:
        absolute = (_project_root() / relative).resolve()
        if absolute.is_relative_to(_generated_root()) and absolute.is_file():
            try:
                absolute.unlink()
            except OSError:
                pass
    return True


def resolve_artifact(artifact_id: str) -> Optional[dict[str, Any]]:
    return get_artifact(artifact_id)
