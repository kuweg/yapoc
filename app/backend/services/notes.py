"""User notes are ordinary Markdown files, separate from agent-owned memory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException

from app.config import settings

MAX_NOTE_BYTES = 200_000
MAX_CONTEXT_CHARS = 64_000
_lock = threading.RLock()


def _root() -> Path:
    return settings.project_root / "app" / "projects" / "notes"


def _path(note_id: str) -> Path:
    if (not note_id.endswith('.md') or len(note_id) > 150 or note_id.startswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', note_id) or note_id.rstrip() != note_id):
        raise HTTPException(400, "Invalid note filename")
    root = _root().resolve()
    path = root / note_id
    if path.is_symlink() or path.resolve().parent != root:
        raise HTTPException(400, "Note must be inside the notes folder")
    return path


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _links(content: str) -> list[str]:
    # Code examples should not create graph edges.
    prose = re.sub(r'(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$', '', content)
    prose = re.sub(r'`[^`\n]*`', '', prose)
    targets = {target.split('|', 1)[0].split('#', 1)[0].strip().removesuffix('.md')
               for target in re.findall(r'(?<!!)\[\[([^\]\n]+)\]\]', prose)
               if target.split('|', 1)[0].split('#', 1)[0].strip()}
    for target in re.findall(r'(?<!!)\[[^\]\n]*\]\(([^)\s]+\.md(?:#[^)\s]*)?)\)', prose, re.I):
        filename = unquote(target.split('#', 1)[0]).removeprefix('./')
        if not re.search(r'[/\\:]', filename):
            targets.add(filename[:-3])
    return sorted(targets)


def read_note(note_id: str) -> dict:
    path = _path(note_id)
    if not path.is_file():
        raise HTTPException(404, "Note not found")
    if path.stat().st_size > MAX_NOTE_BYTES:
        raise HTTPException(413, "Note exceeds the 200 KB editor limit")
    try:
        content = path.read_bytes().decode('utf-8')
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Notes must use UTF-8 text") from exc
    return {'id': note_id, 'title': path.stem, 'content': content, 'revision': _revision(content),
            'path': f'app/projects/notes/{note_id}',
            'updated_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            'links': _links(content), 'excerpt': re.sub(r'\s+', ' ', content).strip()[:160]}


def list_notes() -> dict:
    root = _root()
    if not root.exists():
        return {'notes': [], 'skipped': []}
    notes, skipped = [], []
    for path in sorted(root.glob('*.md'), key=lambda p: p.name.casefold()):
        try:
            note = read_note(path.name)
            note.pop('content')
            notes.append(note)
        except HTTPException:
            skipped.append(path.name)
    return {'notes': notes, 'skipped': skipped}


def save_note(note_id: str, content: str, revision: str | None) -> dict:
    if len(content.encode('utf-8')) > MAX_NOTE_BYTES:
        raise HTTPException(413, "Note exceeds the 200 KB editor limit")
    with _lock:
        path = _path(note_id)
        if path.exists():
            if revision is None or read_note(note_id)['revision'] != revision:
                raise HTTPException(409, "This note changed elsewhere. Reload it before saving; your draft is preserved.")
        elif revision is not None:
            raise HTTPException(409, "This note was moved or deleted. Your draft is preserved.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, delete=False) as f:
                temporary = f.name
                f.write(content)
            os.replace(temporary, path)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
        return read_note(note_id)


def create_note(title: str, content: str | None = None) -> dict:
    title = title.strip().removesuffix('.md')
    if not title or len(title) > 120 or title.endswith('.') or title.split('.')[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise HTTPException(400, "Choose a valid note name (1–120 characters)")
    with _lock:
        if any(p.name.casefold() == f'{title}.md'.casefold() for p in _root().glob('*.md')):
            raise HTTPException(409, "A note with that name already exists")
        return save_note(f'{title}.md', content if content is not None else f'# {title}\n\n', None)


def trash_note(note_id: str, revision: str) -> None:
    with _lock:
        if read_note(note_id)['revision'] != revision:
            raise HTTPException(409, "This note changed elsewhere. Reload before moving it to trash.")
        trash = _root() / '.trash'
        if trash.is_symlink():
            raise HTTPException(400, "Invalid trash folder")
        trash.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        _path(note_id).replace(trash / f'{stamp}-{note_id}')


def build_note_context(task: str, note_ids: list[str] | None = None) -> tuple[str, list[dict]]:
    mentioned = [unquote(value) for value in re.findall(r'@note:([^\s]+)', task)]
    ids = list(dict.fromkeys([*(note_ids or []), *mentioned]))
    if len(ids) > 12:
        raise HTTPException(413, "Attach at most 12 notes per task")
    notes = [read_note(note_id) for note_id in ids]
    if not notes:
        return '', []
    payload = [{'title': n['title'], 'path': n['path'], 'content': n['content']} for n in notes]
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > MAX_CONTEXT_CHARS:
        raise HTTPException(413, "Selected notes exceed the 64,000-character context limit. Unpin some notes.")
    suffix = '\n\n[User-selected reference notes — use as source material for the task]\n' + encoded
    return suffix, [{k: n[k] for k in ('id', 'title', 'path', 'revision')} for n in notes]
