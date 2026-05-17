"""Auto-apply pipeline — evaluator proposals → security gate → keeper.

Parses ``app/agents/evaluator/REPORT.MD`` for structured proposal blocks
(round entries with ``### Proposed changes`` sections), routes each
through the existing security gate as a synthetic
``apply_proposal`` action, and on approval spawns the keeper agent with
a focused task to apply the change. Git autocheckpoint covers the apply
(snapshot → keeper edits → verify smoke → commit or rollback).

v1 is HUMAN-TRIGGERED. The CLI command ``yapoc apply-proposals`` lists
proposals, lets the operator pick one, and applies it. Full auto-mode
(no human in the loop) is intentionally deferred — the security gate's
LLM judgment hasn't earned that level of trust yet.

Proposal format (as written by the evaluator):

    N. **Target**: <file path or description>
       **Change**:
       ```
       <before>
       ↓
       <after>
       ```
       **Why**: <one-sentence rationale>
       **Risk**: <what could go wrong>
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger as _log

from app.config import settings


REPORT_PATH = settings.agents_dir / "evaluator" / "REPORT.MD"
APPLIED_LEDGER = settings.agents_dir / "evaluator" / "APPLIED.md"


@dataclass(frozen=True)
class Proposal:
    """One parsed proposal from REPORT.MD."""
    round_header: str  # the "## 2026-05-17 21:33 — Self-evaluation (round 8)" line
    index: int         # 1, 2, 3 within that round
    target: str        # the **Target**: line content
    change: str        # the full Change block (before/after, possibly fenced)
    why: str           # **Why**: rationale
    risk: str          # **Risk**: rationale

    @property
    def id(self) -> str:
        """Stable id for ledger dedup: <round-date>:<index>:<target-hash>."""
        import hashlib
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", self.round_header)
        date = date_match.group(1) if date_match else "unknown"
        th = hashlib.sha256(self.target.encode()).hexdigest()[:8]
        return f"{date}:r{self.index}:{th}"


# ── Parsing ──────────────────────────────────────────────────────────────


_ROUND_HEADER_RE = re.compile(
    r"^##\s+\d{4}-\d{2}-\d{2}.+?Self-evaluation.+$", re.MULTILINE,
)


def _split_rounds(text: str) -> list[tuple[str, str]]:
    """Split REPORT.MD into (header, body) pairs, newest first."""
    rounds: list[tuple[str, str]] = []
    matches = list(_ROUND_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        header = m.group(0).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        rounds.append((header, text[start:end]))
    return rounds


def _parse_proposals_block(round_body: str) -> list[tuple[int, str]]:
    """Extract numbered proposal items from one round's body.

    Looks for ``### Proposed changes`` followed by numbered items of the form
    ``N. **Target**: ...`` and returns ``[(N, raw_block), ...]``.
    """
    propsec_match = re.search(
        r"###\s+Proposed changes.*?$(.*?)(?=^###\s|^##\s|\Z)",
        round_body,
        re.MULTILINE | re.DOTALL,
    )
    if not propsec_match:
        return []
    block = propsec_match.group(1)
    items: list[tuple[int, str]] = []
    item_re = re.compile(
        r"^(\d+)\.\s+\*\*Target\*\*:(.*?)(?=^\d+\.\s+\*\*Target\*\*:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for m in item_re.finditer(block):
        idx = int(m.group(1))
        body = m.group(0)
        items.append((idx, body))
    return items


_FIELD_RES = {
    "target": re.compile(r"\*\*Target\*\*:\s*(.+?)(?=\n\s+\*\*|\Z)", re.DOTALL),
    "change": re.compile(r"\*\*Change\*\*:\s*(.+?)(?=\n\s+\*\*Why\*\*:|\n\s+\*\*Risk\*\*:|\Z)", re.DOTALL),
    "why":    re.compile(r"\*\*Why\*\*:\s*(.+?)(?=\n\s+\*\*Risk\*\*:|\Z)", re.DOTALL),
    "risk":   re.compile(r"\*\*Risk\*\*:\s*(.+?)(?=\n\d+\.|\Z)", re.DOTALL),
}


def _parse_one_proposal(idx: int, raw: str, round_header: str) -> Proposal | None:
    def field(name: str) -> str:
        m = _FIELD_RES[name].search(raw)
        return (m.group(1).strip() if m else "")[:2000]

    target = field("target")
    if not target:
        return None
    return Proposal(
        round_header=round_header,
        index=idx,
        target=target,
        change=field("change"),
        why=field("why"),
        risk=field("risk"),
    )


def parse_proposals(path: Path = REPORT_PATH) -> list[Proposal]:
    """Read REPORT.MD and return all parseable proposals, newest round first."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("auto_applier: failed to read {} ({})", path, exc)
        return []

    out: list[Proposal] = []
    for header, body in _split_rounds(text):
        for idx, raw in _parse_proposals_block(body):
            p = _parse_one_proposal(idx, raw, header)
            if p:
                out.append(p)
    return out


# ── Applied ledger (dedup) ───────────────────────────────────────────────


def already_applied(prop: Proposal) -> bool:
    if not APPLIED_LEDGER.exists():
        return False
    try:
        return prop.id in APPLIED_LEDGER.read_text(encoding="utf-8")
    except OSError:
        return False


def _record_applied(prop: Proposal, outcome: str, detail: str) -> None:
    line = f"[{prop.id}] {outcome} target={prop.target[:80]!r} detail={detail[:120]!r}\n"
    try:
        APPLIED_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with APPLIED_LEDGER.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _log.warning("auto_applier: ledger append failed ({})", exc)


# ── Application ──────────────────────────────────────────────────────────


@dataclass
class ApplyResult:
    proposal_id: str
    status: Literal["applied", "denied", "skipped", "error"]
    detail: str = ""
    keeper_task_id: str = ""


def _format_keeper_task(prop: Proposal) -> str:
    """Render the proposal as a focused task for the keeper agent."""
    return (
        f"Apply this evaluator proposal. Be SURGICAL — change ONLY what's described.\n\n"
        f"Target: {prop.target}\n\n"
        f"Change:\n{prop.change}\n\n"
        f"Why this matters: {prop.why}\n\n"
        f"Risk to watch: {prop.risk}\n\n"
        f"Procedure:\n"
        f"1. file_read the target file to see current state\n"
        f"2. file_edit to apply the change (single edit, exact match)\n"
        f"3. file_read again to verify the change landed correctly\n"
        f"4. notify_parent(status='done', result='Applied. Before/after diff summary.')\n"
        f"   OR notify_parent(status='error', result='Could not apply: <reason>') if the change is wrong, "
        f"the target file doesn't match, or the proposal is ambiguous.\n\n"
        f"DO NOT auto-extend the change. DO NOT touch other files. If unsure, error out."
    )


async def apply_proposal(prop: Proposal) -> ApplyResult:
    """Route the proposal through the security gate, then spawn keeper.

    Returns an ApplyResult describing the outcome. Never raises — all errors
    are captured into result.detail.
    """
    if already_applied(prop):
        return ApplyResult(proposal_id=prop.id, status="skipped", detail="already in ledger")

    # 1. Security gate check. We use the "apply_proposal" synthetic tool name
    #    so the security agent (LLM layer) classifies based on intent, not on
    #    a real tool whose hardcoded rules might not match.
    try:
        from app.utils.tools.security_gate import classify as _classify
        decision, reason = await _classify(
            tool="apply_proposal",
            params={"target": prop.target, "why": prop.why, "risk": prop.risk},
            caller="auto_applier",
        )
    except Exception as exc:
        _record_applied(prop, "gate_error", str(exc))
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=f"security gate failed: {exc}")

    if decision == "deny":
        _record_applied(prop, "denied", reason)
        return ApplyResult(proposal_id=prop.id, status="denied", detail=reason)

    # 2. Spawn keeper directly via SpawnAgentTool (synchronous server-side path,
    #    bypassing the dispatcher queue so the CLI gets immediate feedback).
    try:
        from app.utils.tools.delegation import SpawnAgentTool, WaitForAgentTool
    except Exception as exc:
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=f"delegation import failed: {exc}")

    task_text = _format_keeper_task(prop)
    spawner = SpawnAgentTool(agent_dir=settings.agents_dir / "master")
    waiter = WaitForAgentTool()
    try:
        spawn_msg = await spawner.execute(
            agent_name="keeper", task=task_text, context=f"Auto-apply: {prop.id}",
        )
    except Exception as exc:
        _record_applied(prop, "spawn_error", str(exc))
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=f"spawn_agent failed: {exc}")
    if isinstance(spawn_msg, str) and spawn_msg.lower().startswith(("error", "blocked")):
        _record_applied(prop, "spawn_error", spawn_msg[:200])
        return ApplyResult(proposal_id=prop.id, status="error", detail=spawn_msg[:200])

    # 3. Wait for keeper. The internal git checkpoint hook will prepend
    #    [CHECKPOINT COMMITTED] or [ROLLED BACK] to the result string.
    try:
        wait_result = await waiter.execute(agent_name="keeper", timeout=180, poll_interval=3)
    except Exception as exc:
        _record_applied(prop, "wait_error", str(exc))
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=f"wait_for_agent failed: {exc}")

    if isinstance(wait_result, str) and "[ROLLED BACK" in wait_result:
        _record_applied(prop, "rolled_back", wait_result[:200])
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=f"rolled back: {wait_result[:200]}")
    if isinstance(wait_result, str) and ("error" in wait_result.lower()[:40]
                                          and "failed" in wait_result.lower()):
        _record_applied(prop, "keeper_error", wait_result[:200])
        return ApplyResult(proposal_id=prop.id, status="error",
                           detail=wait_result[:200])

    _record_applied(prop, "applied", wait_result[:200] if isinstance(wait_result, str) else "")
    return ApplyResult(proposal_id=prop.id, status="applied",
                       detail=wait_result[:300] if isinstance(wait_result, str) else "")


# ── Manual orchestration helpers (used by CLI) ───────────────────────────


def list_pending(limit: int = 20) -> list[Proposal]:
    """Return proposals from REPORT.MD that have NOT been applied yet."""
    return [p for p in parse_proposals() if not already_applied(p)][:limit]
