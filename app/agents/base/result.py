"""Structured sub-agent result contract.

Downstream agents that consume a peer's output should parse it
deterministically instead of relying on free text. This module defines a
single typed result schema and a backward-compatible coercion layer so any
existing free-text result still parses cleanly.

Contract::

    {status, summary, files[], artifacts[], details}

- ``status``: one of ``"done"`` | ``"error"`` | ``"partial"`` | ``"timeout"``
- ``summary``: one-line, model-friendly human summary of what happened
- ``files``: list of file paths the subtask created, edited, or reads
- ``artifacts``: list of structured artifact dicts (name/type/path/url, ...)
- ``details``: free-text fallback capturing anything that didn't fit in the
  structured fields (often the raw peer output when it wasn't JSON)

``parse_result`` accepts either a JSON payload following the contract or
plain free text. JSON is preferred when present and carries a ``status``
key; anything else (including malformed JSON or JSON without ``status``)
is coerced into ``AgentResult(status="done", summary=<raw text>)`` so
older free-text sub-agents keep working unchanged.
"""

from dataclasses import dataclass, field
from typing import Any

import json


@dataclass
class AgentResult:
    """Typed result of a delegated subtask."""

    status: str = "done"
    summary: str = ""
    files: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "files": list(self.files),
            "artifacts": list(self.artifacts),
            "details": self.details,
        }


_VALID_STATUSES = {"done", "error", "partial", "timeout"}


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        nl = stripped.find("\n")
        if nl == -1:
            return stripped[len("```"):].strip()
        body = stripped[nl + 1:].rstrip()
        if body.endswith("```"):
            body = body[:-3].rstrip()
        return body.strip()
    return stripped


def parse_result(text: str) -> AgentResult:
    source = _strip_code_fences(text)

    obj: Any = None
    try:
        obj = json.loads(source)
    except (json.JSONDecodeError, TypeError, ValueError):
        obj = None

    if isinstance(obj, dict) and "status" in obj:
        status = str(obj.get("status", "done"))
        if status not in _VALID_STATUSES:
            status = "done"

        def _as_strlist(v: Any) -> list[str]:
            if isinstance(v, list):
                return [str(x) for x in v if x is not None]
            if isinstance(v, str) and v.strip():
                return [x.strip() for x in v.split(",") if x.strip()]
            return []

        def _as_artifactlist(v: Any) -> list[dict[str, Any]]:
            if not isinstance(v, list):
                return []
            out: list[dict[str, Any]] = []
            for item in v:
                if isinstance(item, dict):
                    out.append({str(k): value for k, value in item.items()})
            return out

        summary = str(obj.get("summary", "") or "")
        if not summary:
            summary = text.strip()

        return AgentResult(
            status=status,
            summary=summary,
            files=_as_strlist(obj.get("files")),
            artifacts=_as_artifactlist(obj.get("artifacts")),
            details=str(obj.get("details", "") or ""),
        )

    return AgentResult(status="done", summary=text)


def to_result_json(result: AgentResult, compact: bool = True) -> str:
    if compact:
        return json.dumps(result.to_dict(), separators=(",", ":"), ensure_ascii=False)
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
