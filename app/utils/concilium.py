"""Concilium: Multi-Agent Deliberation Framework for YAPOC.

Concilium is a temporary agent bundle that enables structured multi-perspective
review of plans before execution. It is spawned by Master when a task exceeds
a complexity threshold (>=9) or when explicitly requested.

Usage:
    from app.utils.concilium import ConciliumOrchestrator
    
    orchestrator = ConciliumOrchestrator(session_id="...")
    result = await orchestrator.deliberate(plan_text="...")
    # result.status: "approved" | "rejected" | "escalated"
    # result.approved_plan: str (revised plan if approved)
    # result.escalation_summary: dict (if escalated)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from app.config import settings
from app.utils.adapters import AgentConfig, get_adapter

# ── Constants ────────────────────────────────────────────────────────────────

# Anchor to the project root via settings so the orchestrator always
# writes to the same place regardless of the backend's CWD. Relative
# `Path("app/agents/concilium")` previously dropped sessions into
# whatever directory uvicorn happened to launch from (e.g. it picked up
# `app/frontend/app/agents/concilium/` after a frontend toolchain ran in
# that dir), breaking the router's session list and the UI's history.
from app.config import settings as _concilium_settings
CONCILIUM_DIR = _concilium_settings.agents_dir / "concilium"
MAX_ROUNDS = 3
CONSENSUS_THRESHOLD = 0.8  # 80% weighted score required

# Counselor role definitions
COUNSELOR_ROLES = {
    "architect": {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "focus": "Technical soundness, scalability, design patterns",
        "weight": 0.30,
        "prompt": """You are the Architect counselor in a Concilium deliberation.
Your role is to evaluate plans for technical soundness, scalability, and architectural coherence.

Evaluate the plan below and produce a structured critique:
1. **Issues found** (categorized: blocker / major / minor / suggestion)
2. **Specific concerns** with line/step references
3. **Recommended changes** (concrete and actionable)
4. **Vote**: approve / revise / reject
5. **Confidence**: 0.0-1.0

Focus on: missing dependencies, integration points, scalability, anti-patterns (god objects, tight coupling), alternative approaches if fundamentally flawed.""",
    },
    "critic": {
        "model": "deepseek-chat",
        "temperature": 0.4,
        "focus": "Edge cases, failure modes, logical gaps",
        "weight": 0.25,
        "prompt": """You are the Critic counselor in a Concilium deliberation.
Your role is to find edge cases, failure modes, and logical gaps in plans.

Evaluate the plan below and produce a structured critique:
1. **Issues found** (categorized: blocker / major / minor / suggestion)
2. **Unstated assumptions** the plan makes
3. **Edge cases** not addressed
4. **Pre-mortem**: if this plan fails, what caused it?
5. **Vote**: approve / revise / reject
6. **Confidence**: 0.0-1.0

Focus on: logical consistency, ambiguous requirements, failure scenarios, missing error handling.""",
    },
    "security": {
        "model": "deepseek-chat",
        "temperature": 0.0,
        "focus": "Vulnerabilities, credential handling, access control",
        "weight": 0.20,
        "prompt": """You are the Security Reviewer counselor in a Concilium deliberation.
Your role is to identify security vulnerabilities, credential exposure risks, and sandbox violations.

Evaluate the plan below and produce a structured critique:
1. **Issues found** (categorized: blocker / major / minor / suggestion)
2. **Hardcoded credentials or secrets** in the plan
3. **File operations** that could expose sensitive data
4. **Sandbox restriction violations**
5. **Recommended hardening steps**
6. **Vote**: approve / revise / reject
7. **Confidence**: 0.0-1.0

Focus on: .env files, API keys, config mutations, file permission changes, credential rotation.""",
    },
    "cost_analyst": {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "focus": "Resource usage, token consumption, cost efficiency",
        "weight": 0.15,
        "prompt": """You are the Cost Analyst counselor in a Concilium deliberation.
Your role is to estimate resource usage and identify cost optimization opportunities.

Evaluate the plan below and produce a structured critique:
1. **Issues found** (categorized: blocker / major / minor / suggestion)
2. **Estimated LLM calls** the plan will require
3. **Estimated token consumption** and cost
4. **Expensive operations** (large file reads, multi-agent spawns)
5. **Cost optimization suggestions** (batching, caching, cheaper models)
6. **Vote**: approve / revise / reject
7. **Confidence**: 0.0-1.0

Focus on: API call counts, token estimates, model selection, budget thresholds.""",
    },
    "ux_advocate": {
        "model": "deepseek-chat",
        "temperature": 0.3,
        "focus": "User experience, error handling, rollback paths",
        "weight": 0.10,
        "prompt": """You are the UX Advocate counselor in a Concilium deliberation.
Your role is to evaluate how the plan affects end-user experience and system reliability.

Evaluate the plan below and produce a structured critique:
1. **Issues found** (categorized: blocker / major / minor / suggestion)
2. **User experience impact** of the proposed changes
3. **Error handling adequacy**
4. **Rollback/recovery paths** — are they considered?
5. **System consistency** — could the plan leave things in a bad state?
6. **Vote**: approve / revise / reject
7. **Confidence**: 0.0-1.0

Focus on: error messages, progress indicators, confirmation steps, recovery procedures.""",
    },
}


# ── Data types ───────────────────────────────────────────────────────────────

class Vote(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class DeliberationStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


@dataclass
class CounselorCritique:
    role: str
    issues: list[dict]  # [{severity, description, reference}]
    vote: Vote
    confidence: float
    raw_output: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DeliberationRound:
    round_number: int
    critiques: dict[str, CounselorCritique] = field(default_factory=dict)
    synthesis: str = ""
    revised_plan: str = ""
    weighted_score: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""


@dataclass
class DeliberationResult:
    status: DeliberationStatus
    approved_plan: str = ""
    escalation_summary: dict | None = None
    rounds: list[DeliberationRound] = field(default_factory=list)
    session_id: str = ""
    duration_s: float = 0.0
    total_cost_usd: float = 0.0


# ── Logging helpers ──────────────────────────────────────────────────────────

def _log_event(session_id: str, event_type: str, data: dict) -> None:
    """Write a structured event to the Concilium log file for observability."""
    log_dir = CONCILIUM_DIR / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "events.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "type": event_type,
        "data": data,
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _write_live_md(session_id: str, phase: str, detail: str) -> None:
    """Write to LIVE.MD for the real-time trace stream."""
    log_dir = CONCILIUM_DIR / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    live_path = log_dir / "LIVE.MD"
    live_path.write_text(
        f"[{datetime.now(timezone.utc).isoformat()}] [{phase}] {detail}\n"
    )


# Terminal deliberation states — used by both the orchestrator (to know
# when to mark STATUS.json as completed) and the router/UI (to know when
# polling can stop). Centralized here so updates land in one place.
_CONCILIUM_TERMINAL_STATES: frozenset[str] = frozenset({
    "approved", "rejected", "escalated", "error",
})


def _write_status(
    session_id: str,
    state: str,
    *,
    current_round: int = 0,
    max_rounds: int = 0,
    active_roles: list[str] | None = None,
    error: str = "",
    extra: dict | None = None,
) -> None:
    """Atomically write STATUS.json for a Concilium session.

    Replaces the prior "infer status from events.jsonl" pattern in the
    router (`_infer_status`) — that worked, but only when polled, and
    couldn't represent the gap between deliberation-kicked-off and
    first-round-event. With this file:

      - `state` is one of: ``spawning``, ``running``,
        ``approved``, ``rejected``, ``escalated``, ``error``.
      - `current_round` ticks as the orchestrator advances.
      - `started_at` is preserved across writes; `updated_at` always
        refreshes.
      - Terminal states stamp `completed_at`.

    Best-effort: write failures are swallowed so a flaky disk can't
    crash the orchestrator loop. The UI already has fallback paths
    (events.jsonl scan) for the rare case STATUS.json goes missing.
    """
    log_dir = CONCILIUM_DIR / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    status_path = log_dir / "STATUS.json"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Preserve started_at across writes if a prior STATUS.json exists.
    started_at = now
    if status_path.exists():
        try:
            prior = json.loads(status_path.read_text())
            started_at = prior.get("started_at", now)
        except (OSError, json.JSONDecodeError):
            pass

    payload: dict = {
        "session_id": session_id,
        "state": state,
        "started_at": started_at,
        "updated_at": now,
        "current_round": current_round,
        "max_rounds": max_rounds,
        "active_roles": active_roles or [],
    }
    if state in _CONCILIUM_TERMINAL_STATES:
        payload["completed_at"] = now
    if error:
        payload["error"] = error[:500]
    if extra:
        payload.update(extra)

    try:
        # Atomic write via tmp + rename.
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(status_path)
    except OSError:
        # Best-effort — don't ever crash deliberation because of a disk
        # write failure here. The UI's event-inference fallback survives.
        return


def _persist_result(session_id: str, result: "DeliberationResult", plan_text: str) -> None:
    """Snapshot the final DeliberationResult to result.json so the UI can re-load it later."""
    log_dir = CONCILIUM_DIR / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": result.session_id,
        "status": result.status.value,
        "rounds_completed": len(result.rounds),
        "duration_s": result.duration_s,
        "total_cost_usd": result.total_cost_usd,
        "approved_plan": result.approved_plan or None,
        "escalation_summary": result.escalation_summary,
        "plan_text": plan_text,
        "rounds": [
            {
                "round_number": r.round_number,
                "weighted_score": r.weighted_score,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "critiques": {
                    role: {
                        "role": c.role,
                        "vote": c.vote.value,
                        "confidence": c.confidence,
                        "issues": c.issues,
                        "timestamp": c.timestamp,
                    }
                    for role, c in r.critiques.items()
                },
            }
            for r in result.rounds
        ],
        "persisted_at": datetime.now(timezone.utc).isoformat(),
    }
    (log_dir / "result.json").write_text(json.dumps(payload, indent=2))


def _notify_master(
    session_id: str,
    result: "DeliberationResult",
    plan_text: str,
) -> None:
    """Push a deliberation outcome into master's notification queue.

    Without this, the orchestrator finishes silently — master never sees
    that a concilium session it (or the UI) requested has produced a
    result. The notification surfaces on master's next ``handle_task_stream``
    turn as ``[SYSTEM NOTIFICATION — sub-agent results]`` so master can
    apply an approved plan, surface an escalation to the user, or
    learn from a rejection.

    The body is a compact, human-readable summary — anything master needs
    more detail on it can pull from ``result.json`` directly.

    Best-effort: import + call is wrapped so a backend that doesn't have
    the notification_queue available (e.g. a unit test) doesn't break the
    orchestrator's return path.
    """
    try:
        from app.backend.services.notification_queue import notification_queue
    except Exception:
        return

    status = result.status.value
    duration = result.duration_s
    rounds = len(result.rounds)

    # Compose a one-page summary master can scan in a single turn.
    lines: list[str] = [
        f"Concilium session {session_id} — {status.upper()}",
        f"Rounds: {rounds} | Duration: {duration:.1f}s",
    ]
    plan_preview = (plan_text or "").strip().splitlines()
    if plan_preview:
        lines.append(f"Plan: {plan_preview[0][:160]}")
    if result.status == DeliberationStatus.APPROVED and result.approved_plan:
        approved_preview = result.approved_plan.strip().splitlines()
        if approved_preview:
            lines.append(f"Approved plan first line: {approved_preview[0][:160]}")
        lines.append(f"Next step: implement the approved plan (see app/agents/concilium/{session_id}/result.json for full text).")
    elif result.escalation_summary:
        rec = result.escalation_summary.get("recommendation", "")
        if rec:
            # Truncate so master's context doesn't bloat — the full JSON is
            # one file_read away.
            lines.append("")
            lines.append(rec[:1200])
        lines.append("")
        lines.append(f"Full report: app/agents/concilium/{session_id}/result.json")

    summary = "\n".join(lines)

    try:
        notification_queue.enqueue(
            parent_agent="master",
            child_agent="concilium",
            status="done" if result.status == DeliberationStatus.APPROVED else "error",
            result=summary if result.status == DeliberationStatus.APPROVED else "",
            error=summary if result.status != DeliberationStatus.APPROVED else "",
            session_id=session_id,
        )
    except Exception:
        # Don't ever let a notification-queue failure derail the
        # orchestrator's return.
        return


# ── Orchestrator ─────────────────────────────────────────────────────────────

class ConciliumOrchestrator:
    """Orchestrates multi-agent deliberation for a single task.

    Usage:
        orch = ConciliumOrchestrator(session_id="...")
        result = await orch.deliberate(plan_text="...")
    """

    def __init__(
        self,
        session_id: str | None = None,
        max_rounds: int = MAX_ROUNDS,
        counselor_roles: list[str] | None = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.max_rounds = max_rounds
        self.active_roles = counselor_roles or list(COUNSELOR_ROLES.keys())
        self.rounds: list[DeliberationRound] = []
        self.start_time: float = 0.0
        self.total_cost: float = 0.0

        # Ensure log directory exists
        (CONCILIUM_DIR / self.session_id).mkdir(parents=True, exist_ok=True)

    async def deliberate(self, plan_text: str) -> DeliberationResult:
        """Run the full deliberation protocol on a plan.

        Returns a DeliberationResult with the outcome.
        """
        self.start_time = time.monotonic()
        _log_event(self.session_id, "deliberation_started", {
            "plan_length": len(plan_text),
            "roles": self.active_roles,
            "max_rounds": self.max_rounds,
        })
        _write_live_md(self.session_id, "START", f"Deliberation started with {len(self.active_roles)} counselors")
        # First STATUS.json write — the UI now has something to poll
        # before the first round even starts.
        _write_status(
            self.session_id, "running",
            current_round=0, max_rounds=self.max_rounds,
            active_roles=self.active_roles,
        )

        current_plan = plan_text

        for round_num in range(1, self.max_rounds + 1):
            _write_live_md(self.session_id, f"ROUND_{round_num}", "Starting round")
            _write_status(
                self.session_id, "running",
                current_round=round_num, max_rounds=self.max_rounds,
                active_roles=self.active_roles,
            )

            round_result = await self._run_round(round_num, current_plan)
            self.rounds.append(round_result)

            # Check consensus
            if round_result.weighted_score >= CONSENSUS_THRESHOLD:
                # All votes must be approve or revise (not reject)
                rejections = [
                    r for r in round_result.critiques.values()
                    if r.vote == Vote.REJECT
                ]
                if not rejections:
                    _log_event(self.session_id, "approved", {
                        "round": round_num,
                        "score": round_result.weighted_score,
                    })
                    _write_live_md(self.session_id, "APPROVED", f"Plan approved in round {round_num}")

                    duration = time.monotonic() - self.start_time
                    result = DeliberationResult(
                        status=DeliberationStatus.APPROVED,
                        approved_plan=round_result.revised_plan or current_plan,
                        rounds=self.rounds,
                        session_id=self.session_id,
                        duration_s=duration,
                        total_cost_usd=self.total_cost,
                    )
                    _persist_result(self.session_id, result, plan_text)
                    _write_status(
                        self.session_id, "approved",
                        current_round=round_num, max_rounds=self.max_rounds,
                        active_roles=self.active_roles,
                        extra={"score": round_result.weighted_score,
                               "duration_s": duration},
                    )
                    _notify_master(self.session_id, result, plan_text)
                    return result

            # If rejected by any counselor, escalate
            rejections = [
                r for r in round_result.critiques.values()
                if r.vote == Vote.REJECT
            ]
            if rejections:
                _log_event(self.session_id, "rejected", {
                    "round": round_num,
                    "rejections": [r.role for r in rejections],
                })
                _write_live_md(self.session_id, "REJECTED", f"Plan rejected in round {round_num}")

                duration = time.monotonic() - self.start_time
                result = DeliberationResult(
                    status=DeliberationStatus.REJECTED,
                    rounds=self.rounds,
                    session_id=self.session_id,
                    duration_s=duration,
                    total_cost_usd=self.total_cost,
                    escalation_summary=self._build_escalation_summary(),
                )
                _persist_result(self.session_id, result, plan_text)
                _write_status(
                    self.session_id, "rejected",
                    current_round=round_num, max_rounds=self.max_rounds,
                    active_roles=self.active_roles,
                    extra={"rejected_by": [r.role for r in rejections],
                           "duration_s": duration},
                )
                _notify_master(self.session_id, result, plan_text)
                return result

            # Update plan with revisions for next round
            if round_result.revised_plan:
                current_plan = round_result.revised_plan

        # Max rounds reached without consensus — escalate
        _log_event(self.session_id, "escalated", {
            "rounds_completed": len(self.rounds),
            "final_score": self.rounds[-1].weighted_score if self.rounds else 0,
        })
        _write_live_md(self.session_id, "ESCALATED", f"Max rounds ({self.max_rounds}) reached without consensus")

        duration = time.monotonic() - self.start_time
        result = DeliberationResult(
            status=DeliberationStatus.ESCALATED,
            rounds=self.rounds,
            session_id=self.session_id,
            duration_s=duration,
            total_cost_usd=self.total_cost,
            escalation_summary=self._build_escalation_summary(),
        )
        _persist_result(self.session_id, result, plan_text)
        _write_status(
            self.session_id, "escalated",
            current_round=len(self.rounds),
            max_rounds=self.max_rounds,
            active_roles=self.active_roles,
            extra={"duration_s": duration},
        )
        _notify_master(self.session_id, result, plan_text)
        return result

    async def _run_round(self, round_num: int, plan_text: str) -> DeliberationRound:
        """Execute a single deliberation round.

        Each active counselor role is invoked in parallel via the configured
        default LLM adapter. The counselor returns a structured JSON critique
        which is parsed into a ``CounselorCritique``. The round's weighted
        score is computed from each counselor's vote signal × confidence ×
        role weight (renormalised by the sum of active-role weights so
        partial counselor sets are scored on the same scale).
        """
        round_obj = DeliberationRound(round_number=round_num)
        _log_event(self.session_id, f"round_{round_num}_started", {
            "plan_length": len(plan_text),
            "active_roles": self.active_roles,
        })

        active = [r for r in self.active_roles if r in COUNSELOR_ROLES]
        if not active:
            round_obj.completed_at = datetime.now(timezone.utc).isoformat()
            _log_event(self.session_id, f"round_{round_num}_completed", {
                "critiques_count": 0, "score": 0.0,
                "reason": "no_active_counselors",
            })
            return round_obj

        tasks = [self._invoke_counselor(role, plan_text) for role in active]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_weight = 0.0
        weighted_score = 0.0
        for role, res in zip(active, results):
            weight = float(COUNSELOR_ROLES[role]["weight"])
            total_weight += weight
            if isinstance(res, Exception):
                logger.warning(
                    "Concilium {} round {} counselor {} failed: {}",
                    self.session_id, round_num, role, res,
                )
                critique = CounselorCritique(
                    role=role,
                    issues=[{
                        "severity": "minor",
                        "description": f"counselor call failed: {type(res).__name__}: {res}",
                        "reference": "",
                    }],
                    vote=Vote.REVISE,
                    confidence=0.0,
                    raw_output=str(res),
                )
            else:
                critique = res
            round_obj.critiques[role] = critique
            signal = _vote_signal(critique.vote)
            weighted_score += weight * signal * critique.confidence

        if total_weight > 0:
            round_obj.weighted_score = weighted_score / total_weight

        round_obj.completed_at = datetime.now(timezone.utc).isoformat()

        vote_distribution = {
            v.value: sum(1 for c in round_obj.critiques.values() if c.vote == v)
            for v in Vote
        }
        _log_event(self.session_id, f"round_{round_num}_completed", {
            "critiques_count": len(round_obj.critiques),
            "score": round_obj.weighted_score,
            "votes": vote_distribution,
        })
        _write_live_md(
            self.session_id,
            f"ROUND_{round_num}",
            f"completed: score={round_obj.weighted_score:.2f} votes={vote_distribution}",
        )
        return round_obj

    async def _invoke_counselor(self, role: str, plan_text: str) -> CounselorCritique:
        """Call a single counselor with the role prompt + plan, parse the JSON response."""
        role_cfg = COUNSELOR_ROLES[role]
        system_prompt = role_cfg["prompt"] + _COUNSELOR_OUTPUT_CONTRACT

        # Use the deployment's configured default adapter/model. The
        # role-level "model" in COUNSELOR_ROLES is advisory; deferring to
        # settings keeps the feature usable on whichever provider the user
        # configured via `yapoc init`.
        config = AgentConfig(
            adapter=settings.default_adapter,
            model=settings.default_model,
            temperature=float(role_cfg["temperature"]),
            max_tokens=2048,
        )
        adapter = get_adapter(config)

        t0 = time.monotonic()
        raw = await adapter.complete(
            system_prompt=system_prompt,
            user_message=f"Plan to evaluate:\n\n{plan_text}",
            history=None,
            response_format="json",
        )
        elapsed = time.monotonic() - t0
        _log_event(self.session_id, "counselor_response", {
            "role": role, "elapsed_s": round(elapsed, 3),
            "response_chars": len(raw or ""),
        })
        return _parse_counselor_response(role, raw or "")

    def _build_escalation_summary(self) -> dict:
        """Build an escalation summary from all rounds.

        Now includes the actual critique text (not just counts), the top
        unresolved issues across rejecting/revising counselors, and an
        actionable next-steps section so the user has enough context to
        decide what to do without reading every events.jsonl entry.
        """
        last_round = self.rounds[-1] if self.rounds else None

        # Collect the top issues from counselors who didn't approve in the
        # last round. These are the unresolved blockers — exactly what a
        # reviewer needs to see to decide next steps.
        top_unresolved: list[dict] = []
        if last_round:
            for role, c in last_round.critiques.items():
                if c.vote == Vote.APPROVE:
                    continue
                # Cap per-role issues so the summary stays scannable.
                # ``c.issues`` is ``list[dict]`` with the schema
                # ``{severity, description, reference}``. The dict-get + fallback
                # chain stays defensive so a slightly-different counselor JSON
                # output (e.g. ``text`` instead of ``description``) still lands.
                role_issues = [
                    {
                        "severity": str(i.get("severity", "") or ""),
                        "description": str(
                            i.get("description") or i.get("text") or i.get("issue") or ""
                        )[:400],
                        "reference": str(
                            i.get("reference") or i.get("source") or ""
                        )[:200],
                        "suggestion": str(
                            i.get("suggestion") or i.get("recommendation") or ""
                        )[:400],
                    }
                    for i in (c.issues or [])[:5]
                    if isinstance(i, dict)
                ]
                top_unresolved.append({
                    "role": role,
                    "vote": c.vote.value,
                    "confidence": c.confidence,
                    "issues": role_issues,
                })

        # Per-round vote table — still useful for a quick visual scan.
        round_history = [
            {
                "round": r.round_number,
                "critiques": {
                    role: {
                        "vote": c.vote.value,
                        "confidence": c.confidence,
                        "issues_count": len(c.issues),
                    }
                    for role, c in r.critiques.items()
                },
                "score": r.weighted_score,
            }
            for r in self.rounds
        ]

        # Free-form next-steps recommendation synthesized from the unresolved
        # issues. Cheap (no LLM): bullets the most-severe per-role concern.
        bullets: list[str] = []
        for entry in top_unresolved:
            role = entry["role"]
            for issue in entry["issues"][:2]:
                text = issue.get("description") or issue.get("suggestion") or ""
                if not text:
                    continue
                sev = issue.get("severity")
                prefix = f"({role}, {sev})" if sev else f"({role})"
                bullets.append(f"- {prefix} {text}")
        if bullets:
            next_steps = (
                "Manual review recommended — counselors could not reach consensus.\n\n"
                "Top unresolved issues:\n" + "\n".join(bullets[:8])
            )
        else:
            next_steps = "Manual review recommended — counselors could not reach consensus."

        return {
            "session_id": self.session_id,
            "rounds_completed": len(self.rounds),
            "final_round_score": last_round.weighted_score if last_round else 0.0,
            "round_history": round_history,
            "top_unresolved_issues": top_unresolved,
            "remaining_disagreements": self._find_disagreements(),
            "recommendation": next_steps,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _find_disagreements(self) -> list[dict]:
        """Find unresolved disagreements across rounds."""
        if not self.rounds:
            return []
        last_round = self.rounds[-1]
        disagreements = []
        for role, critique in last_round.critiques.items():
            if critique.vote != Vote.APPROVE:
                disagreements.append({
                    "role": role,
                    "vote": critique.vote.value,
                    "confidence": critique.confidence,
                    "concern": f"{role} did not approve (vote: {critique.vote.value})",
                })
        return disagreements

    def get_round_logs(self, round_number: int | None = None) -> list[dict]:
        """Read logged events for a specific round or all rounds."""
        log_path = CONCILIUM_DIR / self.session_id / "events.jsonl"
        if not log_path.exists():
            return []

        events = []
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if round_number and f"round_{round_number}" not in event.get("type", ""):
                        continue
                    events.append(event)
                except json.JSONDecodeError:
                    continue
        return events

    def get_all_logs(self) -> list[dict]:
        """Read all logged events for this session."""
        return self.get_round_logs()


# ── Counselor response handling ──────────────────────────────────────────────

# Appended to every counselor's role prompt. Asks for a JSON-only response so
# parsing is reliable across providers. Adapters with native JSON mode honour
# response_format="json"; others fall back to a system-prompt nudge.
_COUNSELOR_OUTPUT_CONTRACT = """

OUTPUT CONTRACT — respond with a single JSON object only, no prose, no markdown fences:
{
  "vote": "approve" | "revise" | "reject",
  "confidence": 0.0-1.0,
  "issues": [
    {"severity": "blocker" | "major" | "minor" | "suggestion",
     "description": "...",
     "reference": "step or line number, optional"}
  ],
  "rationale": "1-2 sentences explaining the vote"
}
"""


_VOTE_SIGNAL = {Vote.APPROVE: 1.0, Vote.REVISE: 0.5, Vote.REJECT: 0.0}


def _vote_signal(vote: Vote) -> float:
    return _VOTE_SIGNAL.get(vote, 0.5)


_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$")
_VOTE_RE = re.compile(r'"?vote"?\s*[:=]\s*"?(approve|revise|reject)', re.IGNORECASE)
_CONF_RE = re.compile(r'"?confidence"?\s*[:=]\s*([0-9]*\.?[0-9]+)', re.IGNORECASE)


def _parse_counselor_response(role: str, raw: str) -> CounselorCritique:
    """Parse a counselor LLM response into a CounselorCritique.

    Tries strict JSON first; falls back to regex extraction so a non-conforming
    response still produces a usable critique rather than nuking the round.
    """
    cleaned = (raw or "").strip()
    # Strip surrounding ```json ... ``` fences if the model emitted them.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    data: dict | None = None
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            data = None
    except json.JSONDecodeError:
        # Try to recover the first {...} block in the text.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if not isinstance(data, dict):
                    data = None
            except json.JSONDecodeError:
                data = None

    if data is not None:
        return _critique_from_dict(role, data, raw)

    # Final fallback: regex against the raw text.
    vote_match = _VOTE_RE.search(cleaned)
    conf_match = _CONF_RE.search(cleaned)
    vote = _vote_from_str(vote_match.group(1) if vote_match else "")
    try:
        confidence = float(conf_match.group(1)) if conf_match else 0.4
    except (TypeError, ValueError):
        confidence = 0.4
    confidence = max(0.0, min(1.0, confidence))
    return CounselorCritique(
        role=role,
        issues=[{"severity": "minor",
                 "description": "counselor returned unparseable response; vote recovered via regex",
                 "reference": ""}],
        vote=vote,
        confidence=confidence,
        raw_output=raw,
    )


def _critique_from_dict(role: str, data: dict, raw: str) -> CounselorCritique:
    vote = _vote_from_str(str(data.get("vote", "")))
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    issues_raw = data.get("issues", []) or []
    issues: list[dict] = []
    if isinstance(issues_raw, list):
        for item in issues_raw[:20]:  # cap to keep events.jsonl bounded
            if isinstance(item, dict):
                issues.append({
                    "severity": str(item.get("severity", "minor"))[:30],
                    "description": str(item.get("description", ""))[:500],
                    "reference": str(item.get("reference", ""))[:200],
                })
            else:
                issues.append({
                    "severity": "minor",
                    "description": str(item)[:500],
                    "reference": "",
                })

    return CounselorCritique(
        role=role,
        issues=issues,
        vote=vote,
        confidence=confidence,
        raw_output=raw,
    )


def _vote_from_str(s: str) -> Vote:
    s = (s or "").strip().lower()
    if s.startswith("approve"):
        return Vote.APPROVE
    if s.startswith("reject"):
        return Vote.REJECT
    return Vote.REVISE


# ── Helper: assess task complexity ───────────────────────────────────────────

def assess_complexity(task_description: str) -> int:
    """Heuristic complexity assessment (1-10) based on task description.

    This is a simple keyword-based heuristic. In production, this could
    be replaced by an LLM call.
    """
    score = 1  # base

    indicators = {
        # Length indicators
        "multi-file": 2, "multiple files": 2, "several files": 1,
        "refactor": 2, "restructure": 2, "migrate": 2,
        # Risk indicators
        "security": 2, "credential": 2, "secret": 2, "permission": 1,
        "config": 1, "settings": 1, ".env": 2, "database": 2,
        # Scope indicators
        "new agent": 2, "new feature": 1, "architecture": 2,
        "api": 1, "endpoint": 1, "integration": 1,
        # Complexity indicators
        "async": 1, "parallel": 1, "concurrent": 1,
        "distributed": 2, "microservice": 2,
        "test": 0, "fix": 0, "typo": -1, "comment": -1,
    }

    task_lower = task_description.lower()
    for keyword, delta in indicators.items():
        if keyword in task_lower:
            score += delta

    return max(1, min(10, score))


def assess_risk(task_description: str, affected_files: list[str] | None = None) -> str:
    """Assess risk level: 'low', 'moderate', or 'high'."""
    high_risk_keywords = [
        ".env", "credential", "secret", "password", "token",
        "database", "migration", "delete", "drop",
        "security", "permission", "sudo", "root",
        "production", "deploy", "rollback",
    ]
    task_lower = task_description.lower()
    for kw in high_risk_keywords:
        if kw in task_lower:
            return "high"

    if affected_files:
        for f in affected_files:
            if any(kw in f.lower() for kw in [".env", "settings.py", "agent-settings.json", "secret"]):
                return "high"

    return "moderate" if len(task_description) > 200 else "low"
