"""Periodic session digester — writes structured digests of long chat
sessions to ``app/agents/master/sessions/<sid>.digest.md``.

A "session digest" is a markdown file with this structure (mirrors
``app/agents/librarian/PROMPT.MD`` Mode B):

    ## Session digest — <session_id>
    ### Executive summary (≤ 3 sentences)
    ### Anchor (verbatim first user message)
    ### Topics
    ### Open threads
    ### Structured facts (JSON)

This module runs the LLM call inline rather than spawning the librarian
subprocess agent. The librarian's PROMPT.MD Mode B is still useful for
manual digests via ``spawn_agent("librarian", ...)``; the scheduled tick
just reuses the same prompt template directly to keep the code path
self-contained (no agent process management).

Wired into the FastAPI lifespan as an APScheduler interval job (see
``app/backend/main.py``). Runs every ``settings.session_digest_interval_minutes``.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger as _log

from app.config import settings
from app.utils.adapters import AgentConfig, get_adapter


_DIGEST_SYSTEM_PROMPT = """\
You produce a structured digest of a chat session. Read the conversation \
(provided as JSONL-style messages, one per line) and output ONLY the digest \
content — no preamble, no closing remarks.

Format your output EXACTLY as follows (markdown headers verbatim):

## Session digest

### Executive summary
<no more than 3 sentences: what the session was about, what was accomplished, what's still open>

### Anchor (verbatim first user message)
<paste the first user message exactly as it was — do not paraphrase>

### Topics
- **<topic 1>**: <2-3 sentence digest, preserve file paths and decisions verbatim>
- **<topic 2>**: <…>

### Open threads
- <follow-up that isn't resolved yet>

### Structured facts
```json
{
  "files_touched": ["..."],
  "decisions": ["..."],
  "tools_invoked": ["..."],
  "agents_used": ["..."]
}
```

Rules:
- Anchor MUST be byte-equal to the first user message; no paraphrase.
- A "topic" is a coherent thread (one feature, one bug, one investigation), not a per-turn log.
- An "open thread" is something the session ends on without resolution.
- The facts JSON must be valid and parseable.
- Preserve numeric values, file paths, and tool/agent names exactly.
"""


def _candidates_for_digest() -> list[Path]:
    """Return session JSONLs that need (re-)digesting.

    Criteria:
      - File has more than ``settings.session_digest_min_lines`` lines.
      - Either no ``.digest.md`` exists OR the digest is older than
        ``settings.session_digest_refresh_hours``.
    """
    sessions_dir = settings.agents_dir / "master" / "sessions"
    if not sessions_dir.exists():
        return []
    out: list[Path] = []
    min_lines = int(getattr(settings, "session_digest_min_lines", 200))
    refresh_hours = float(getattr(settings, "session_digest_refresh_hours", 6))
    refresh_seconds = refresh_hours * 3600.0
    now = time.time()
    for jsonl in sorted(sessions_dir.glob("*.jsonl")):
        try:
            line_count = sum(1 for _ in jsonl.open("r", encoding="utf-8"))
        except OSError:
            continue
        if line_count < min_lines:
            continue
        digest = jsonl.with_suffix(".digest.md")
        if digest.exists():
            age = now - digest.stat().st_mtime
            if age < refresh_seconds:
                continue
        out.append(jsonl)
    return out


def _read_transcript(session_path: Path, max_chars: int = 60_000) -> str:
    """Render the session JSONL as a readable transcript for the LLM.

    Bounded to ``max_chars`` so even pathologically long sessions don't
    blow the digest model's context window. Truncation happens from the
    *middle* — first and last halves are preserved so the anchor stays
    intact at the top and the open threads stay intact at the bottom.
    """
    try:
        raw = session_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parts: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        role = str(obj.get("role", "")) or "?"
        content = obj.get("content", "")
        if isinstance(content, list):
            buf: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    buf.append(str(block.get("text", block.get("content", ""))))
                else:
                    buf.append(str(block))
            content = "\n".join(buf)
        parts.append(f"[{role}] {str(content).strip()}")
    rendered = "\n\n".join(parts)
    if len(rendered) <= max_chars:
        return rendered
    half = max_chars // 2
    return (
        rendered[:half]
        + f"\n\n[… {len(rendered) - max_chars} chars elided from middle …]\n\n"
        + rendered[-half:]
    )


async def _generate_digest(session_id: str, transcript: str) -> str | None:
    """LLM call: produce the digest markdown for one session.

    Uses ``settings.context_compact_model`` (haiku) when Anthropic is
    configured; otherwise falls back to the project's default adapter.
    Returns None on failure (the digester will retry on the next tick).
    """
    if settings.anthropic_api_key:
        config = AgentConfig(
            adapter="anthropic",
            model=settings.context_compact_model,
            temperature=0.2,
            max_tokens=2048,
        )
    else:
        config = AgentConfig(
            adapter=settings.default_adapter,
            model=settings.default_model,
            temperature=0.2,
            max_tokens=2048,
        )
    adapter = get_adapter(config)
    user_msg = (
        f"Session id: {session_id}\n\n"
        "Below is the session transcript. Produce the digest as specified.\n\n"
        "---\n\n" + transcript
    )
    try:
        return await adapter.complete(
            system_prompt=_DIGEST_SYSTEM_PROMPT,
            user_message=user_msg,
            history=[],
        )
    except Exception as exc:
        _log.warning("session_digester: LLM call failed for {}: {}", session_id, exc)
        return None


def _write_digest(session_id: str, body: str) -> Path | None:
    sessions_dir = settings.agents_dir / "master" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session_id}.digest.md"
    try:
        header = (
            f"<!-- generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"by session_digester -->\n\n"
        )
        path.write_text(header + body.strip() + "\n", encoding="utf-8")
        return path
    except OSError as exc:
        _log.warning("session_digester: write failed for {}: {}", session_id, exc)
        return None


async def digest_one(session_path: Path) -> Path | None:
    """End-to-end: read transcript, LLM-digest, write file. Returns the
    written path or None on failure."""
    sid = session_path.stem
    transcript = await asyncio.to_thread(_read_transcript, session_path)
    if not transcript.strip():
        return None
    body = await _generate_digest(sid, transcript)
    if not body:
        return None
    return _write_digest(sid, body)


async def session_digester_tick() -> None:
    """APScheduler tick — digest at most one candidate per run.

    Picks the session with the oldest (or missing) digest first so the
    work cycles through all long sessions over a few ticks instead of
    hitting the LLM for every candidate at once.
    """
    try:
        candidates = await asyncio.to_thread(_candidates_for_digest)
    except Exception as exc:
        _log.warning("session_digester: candidate scan failed: {}", exc)
        return
    if not candidates:
        return
    candidates.sort(
        key=lambda p: (
            p.with_suffix(".digest.md").stat().st_mtime
            if p.with_suffix(".digest.md").exists()
            else 0
        )
    )
    target = candidates[0]
    sid = target.stem
    _log.info(
        "session_digester: {} candidate(s); digesting oldest: {}",
        len(candidates), sid,
    )
    written = await digest_one(target)
    if written:
        _log.info("session_digester: wrote digest → {}", written)
