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

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

# ── Constants ────────────────────────────────────────────────────────────────

CONCILIUM_DIR = Path("app/agents/concilium")
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

        current_plan = plan_text

        for round_num in range(1, self.max_rounds + 1):
            _write_live_md(self.session_id, f"ROUND_{round_num}", "Starting round")

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
                    return DeliberationResult(
                        status=DeliberationStatus.APPROVED,
                        approved_plan=round_result.revised_plan or current_plan,
                        rounds=self.rounds,
                        session_id=self.session_id,
                        duration_s=duration,
                        total_cost_usd=self.total_cost,
                    )

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
                return DeliberationResult(
                    status=DeliberationStatus.REJECTED,
                    rounds=self.rounds,
                    session_id=self.session_id,
                    duration_s=duration,
                    total_cost_usd=self.total_cost,
                    escalation_summary=self._build_escalation_summary(),
                )

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
        return DeliberationResult(
            status=DeliberationStatus.ESCALATED,
            rounds=self.rounds,
            session_id=self.session_id,
            duration_s=duration,
            total_cost_usd=self.total_cost,
            escalation_summary=self._build_escalation_summary(),
        )

    async def _run_round(self, round_num: int, plan_text: str) -> DeliberationRound:
        """Execute a single deliberation round.

        In a real implementation, this spawns counselor agents via
        spawn_agent/wait_for_agent. For now, it simulates the round
        structure and logs the events.
        """
        round_start = DeliberationRound(round_number=round_num)
        _log_event(self.session_id, f"round_{round_num}_started", {
            "plan_length": len(plan_text),
        })

        # In production, this would spawn counselor agents in parallel:
        # for role in self.active_roles:
        #     spawn_agent(f"concilium_{role}_{self.session_id}", ...)
        #     wait_for_agent(...)
        #
        # For now, we record the round structure and return.
        # The actual agent spawning is done by Master via the DAG executor.

        round_start.completed_at = datetime.now(timezone.utc).isoformat()
        _log_event(self.session_id, f"round_{round_num}_completed", {
            "critiques_count": len(round_start.critiques),
            "score": round_start.weighted_score,
        })

        return round_start

    def _build_escalation_summary(self) -> dict:
        """Build an escalation summary from all rounds."""
        return {
            "session_id": self.session_id,
            "rounds_completed": len(self.rounds),
            "round_history": [
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
            ],
            "remaining_disagreements": self._find_disagreements(),
            "recommendation": "Manual review recommended — counselors could not reach consensus.",
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
