"""Concilium: Synthesis-first Multi-Agent Deliberation Engine for YAPOC.

Concilium is a temporary-agent bundle that lets several specialist
counselors (architect, critic, security, cost_analyst, ux_advocate)
collectively DRAFT an executable plan for Master rather than merely
vote-gate a pre-drafted plan.

Redesign (synthesis-first). The protocol is three phases:

  Phase A "contribution"  - each active role receives the raw task + a
           role-shape brief and RETURNS a specialist contribution block
           {proposals[], risks_to_watch[], questions[]}. No votes here:
           roles PRODUCE material, they do not critique.

  Phase B "convergence" (bounded) - the synthesizer (the architect, per
           Concilium convention) reconciles the roles' contributions and
           folds any reviewer notes into ONE coherent markdown plan body.
           Contributions are the building material; dissent notes act as
           edit instructions.

  Phase C "verification"   - every role reviews the synthesized plan and
           returns {vote, support, note_type, notes, blockers}. A pass
           converges when support-weighted consensus is reached
           (>= CONSENSUS_THRESHOLD) with no GENUINE hard blocker.

RATCHET-KILLING: progress means the synthesized plan TEXT materially
changed between passes - NOT a fixed 0.80 score. If a reconverge pass
changes nothing material yet dissent persists, we STOP and return the best
converged plan plus a conditions[] list of residual non-blocking concerns.
Escalation is reserved for a GENUINE irreconcilable blocker and emits a
compact structured summary rather than an 87KB verbatim-dedup wall.

Backward-compat: DeliberationResult keeps its historical attributes
(approved_plan = alias of the new plan, escalation_summary = compact dict
or None) so legacy helper scripts (app/agents/concilium/run_deliberation.py
and run_test_deliberation.py) keep running.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.config import settings
from app.utils.adapters import AgentConfig, get_adapter
from app.utils.agent_settings import resolve_agent

# ── Constants ────────────────────────────────────────────────────────────────

# Anchor CONCILIUM to an absolute base (settings.agents_dir) so sessions and
# artifacts always land in the same tree regardless of the backend CWD.
CONCILIUM_DIR = settings.agents_dir / "concilium"
MAX_ROUNDS = 6            # hard cap on total reconcile/verify passes
CONSENSUS_THRESHOLD = 0.8  # 80% support-weighted consensus line
DEFAULT_SYNTHESIZER = "architect"

# ── Counselor roles (synthesis-first stances) ────────────────────────────────
#
# Keys are the DEFAULT roles the backend router and UI surface (kept stable for
# backward-compat). Each entry now describes a role's *productive* identity and
# stance for Phase A contribution rather than a "critique a plan" framing. The
# generic per-phase JSON output contracts are attached by the orchestrator (see
# _PHASE_CONTRACTS). Weight is retained but no longer used to average votes (the
# new flow converges a shared plan instead of averaging independent evaluative
# scores); kept purely so the dataclass/status surface stays stable.
COUNSELOR_ROLES: dict[str, dict[str, Any]] = {
    "architect": {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "focus": "Technical soundness, scalability, design patterns, structure",
        "weight": 0.30,
        "prompt": (
            "You are the Architect counselor in a Concilium synthesis panel. "
            "Your job is to shape how the proposed work should be built so it "
            "is technically sound and architecturally coherent.\n"
            "Contribute concrete build strategies, module/file boundaries, "
            "data-flow and integration points, the sequence the work should be "
            "executed in, and the acceptance checks you want honored. Name "
            "specific technical risks that could undermine the design and the "
            "concrete questions that must be answered before implementation. "
            "Ground every proposal in the actual repository context given. "
            "Prefer discrete, executable steps over philosophy."
        ),
    },
    "critic": {
        "model": "deepseek-chat",
        "temperature": 0.4,
        "focus": "Edge cases, failure modes, logical gaps, ambiguous requirements",
        "weight": 0.25,
        "prompt": (
            "You are the Critic counselor in a Concilium synthesis panel. Your "
            "role is to stress-test what a team is about to build by surfacing "
            "edge cases, unstated assumptions, failure paths, and logical gaps.\n"
            "Contribute a set of concrete design criteria that the eventual plan "
            "must satisfy so it does not break: list failure scenarios and how "
            "the implementation should handle each, ambiguous requirements that "
            "should be pinned down, ordering hazards, and rollback concerns for "
            "the steps the plan proposes. Offer proposals, risks_to_watch, and "
            "questions that make the resulting plan executable and robust."
        ),
    },
    "security": {
        "model": "deepseek-chat",
        "temperature": 0.0,
        "focus": "Credentials, access control, sandbox rules, sensitive data",
        "weight": 0.20,
        "prompt": (
            "You are the Security counselor in a Concilium synthesis panel. Your "
            "job is to make sure the work can be implemented without leaking "
            "secrets or violating the YAPOC security sandbox.\n"
            "You are not gate-keeping: you contribute the security properties the "
            "plan must encode. List concrete rules the implementation must follow "
            "including no hardcoded credentials, never dumping .env contents, no "
            "deletion of protected trees, restricted file operations, and safe "
            "handling of auth tokens. Flag operations that could expose secrets "
            "and the exact guardrails to add. Ship proposals, risks_to_watch, and "
            "questions that keep the eventual plan safe-by-construction."
        ),
    },
    "cost_analyst": {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "focus": "Token spend, model choice, runtime/budget realism",
        "weight": 0.15,
        "prompt": (
            "You are the Cost Analyst counselor in a Concilium synthesis panel. "
            "Your job is to keep the eventual implementation cheap to run.\n"
            "Contribute concrete guidance on how many LLM/agent interactions the "
            "plan implies, which steps should use cheap models, where caching or "
            "batching shrinks spend, and what a reasonable budget envelope for "
            "execution looks like. Call out expensive operations that should be "
            "avoided and the cheaper alternative to encode in the plan. Provide "
            "proposals, risks_to_watch, and questions that keep cost bounded."
        ),
    },
    "ux_advocate": {
        "model": "deepseek-chat",
        "temperature": 0.3,
        "focus": "User impact, error handling, recovery/rollback paths",
        "weight": 0.10,
        "prompt": (
            "You are the UX Advocate counselor in a Concilium synthesis panel. "
            "Your job is to keep the plan honest about how changes touch the "
            "user and the running system.\n"
            "Contribute directives the plan should follow: keep the UI dark-mode "
            "and mobile-first, never silently break an open WebSocket or dev "
            "session, give rollback/recovery paths, and surface progress to the "
            "user rather than hanging. Give proposals for sequencing changes "
            "safely, risks_to_watch around reliability and disruption, and "
            "questions that pin down acceptable impact."
        ),
    },
}

# ── Enums ────────────────────────────────────────────────────────────────────

class Vote(str, Enum):
    APPROVE = "approve"    # full approval
    REVISE = "revise"      # approve-with-notes (soft dissent to fold)
    REJECT = "reject"      # a genuine hard blocker, when truly irreconcilable
    ABSTAIN = "abstain"    # skipped / failed call


class NoteKind(str, Enum):
    CONDITION = "condition"      # non-blocking implementation concern to honor
    REFINEMENT = "refinement"    # concrete edit instruction for the plan
    QUESTION = "question"        # needs answering but not blocking
    BLOCKER = "blocker"          # genuine irreconcilable blocker


class DeliberationStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class Contribution:
    """Phase A output: one role's specialist contribution block."""
    role: str
    proposals: list[str] = field(default_factory=list)
    risks_to_watch: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    raw_output: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CounselNote:
    """A single review note raised against the synthesized plan."""
    role: str
    kind: NoteKind          # condition | refinement | question | blocker
    text: str


@dataclass
class Verdict:
    """Phase C output for one role reviewing the synthesized plan body."""
    role: str
    vote: Vote              # approve / revise / reject (soft dissent folding)
    support: float          # 0.0-1.0 continuous support for the plan as-is
    notes: list[CounselNote] = field(default_factory=list)
    rationale: str = ""
    raw_output: str = ""


@dataclass
class Consensus:
    """Aggregate verification outcome across a Phase C pass."""
    n_approve: int = 0
    n_revise: int = 0
    n_reject: int = 0
    n_abstain: int = 0
    final_support: float = 0.0
    reached: bool = False     # did this pass satisfy the consensus rule?
    blockers: list[dict] = field(default_factory=list)  # genuine blockers
    conditions: list[str] = field(default_factory=list) # residual non-blocking


@dataclass
class DeliberationRound:
    """One bounded convergence/verification pass of the new flow.

    Kept name ``DeliberationRound`` (legacy) but semantically a pass over the
    synthesized plan: stores the synthesized ``plan`` body, the verify consensus
    for that body, and the phase the pass represents for STATUS tracing.
    """
    pass_number: int = 0
    phase: str = ""                # "A_contribute" | "B_synthesize" | "C_verify"
    plan: str = ""                 # the plan body produced / verified this pass
    contributions: dict[str, list[str]] = field(default_factory=dict)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    consensus: Consensus = field(default_factory=Consensus)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""


@dataclass
class DeliberationResult:
    """FIRST-CLASS result contract surfaced via result.json / notifications.

    Schema written to disk (result.json):
      {session_id, status, plan, conditions, blockers, consensus,
       rounds_completed, duration_s, total_cost_usd, contributing_roles}
    Backward-compat convenience: ``approved_plan`` aliases ``plan`` and
    ``escalation_summary`` is a compact dict (only present when escalated).
    """
    status: DeliberationStatus
    plan: str = ""
    conditions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    consensus: Consensus = field(default_factory=Consensus)
    rounds: list[DeliberationRound] = field(default_factory=list)
    contributing_roles: list[str] = field(default_factory=list)
    session_id: str = ""
    duration_s: float = 0.0
    total_cost_usd: float = 0.0

    # ── legacy convenience properties ──────────────────────────────────────
    @property
    def approved_plan(self) -> str:
        """Legacy alias of the converged executitable plan."""
        return self.plan

    @property
    def escalation_summary(self) -> dict | None:
        """Compact escalation summary (None unless genuinely escalated)."""
        if self.status != DeliberationStatus.ESCALATED:
            return None
        return {
            "session_id": self.session_id,
            "status": "escalated",
            "rounds_completed": len(self.rounds),
            "blockers": self.blockers,
            "best_plan_preserved_in_plan": bool(self.plan),
            "recommendation": (
                "Genuinely irreconcilable blocker(s) require manual arbitration. "
                "See result.json for the compact blocker list; the best converged "
                "plan is preserved for reference and may be salvageable after the "
                "blocker is resolved."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Execution engine (appended by Builder to complete the synthesis module)
# ── Phase output contracts ─────────────────────────────────────────────────
#
# Generic JSON contract suffix appended to every producer/reviewer call so the
# model returns structured output the orchestrator can parse reliably. Each
# role's named prompt in COUNSELOR_ROLES supplies the *substance*; these blocks
# supply the *shape* of the reply.
_CONTRIBUTION_CONTRACT = """

Return ONLY JSON with this exact shape (no prose, no markdown fences):
{
  "proposals": ["<concrete improvement/proposal 1>", "..."],
  "risks_to_watch": ["<specific risk to honor at build time>", "..."],
  "questions": ["<open question to resolve before implementation>", "..."]
}"""

_SYNTHESIS_CONTRACT = """

Transform every counselor contribution into ONE coherent, executable markdown
plan body. Reconcile conflicts, drop redundancy, fold risks/questions in as
explicit steps or "Conditions" the implementer must honor. Return ONLY the
final merged plan body as a JSON object:
{
  "plan": "<full merged markdown plan body>"
}"""

_VERIFY_CONTRACT = """

Review the synthesized plan as your role. Do NOT re-litigate concerns the plan
already folds in. Return ONLY JSON:
{
  "vote": "approve" | "soft" | "reject",
  "hard_blocker": true | false,
  "blocker_text": "<ONLY if a GENUINELY irreconcilable blocker; else empty string>",
  "conditions": ["<non-blocking but MUST-be-honored implementation detail>", "..."],
  "dissent": ["<brief residual dissent not blocking>", "..."],
  "rationale": "<one paragraph>"
}
Only set hard_blocker:true for a truly irreconcilable problem that makes the
whole plan unworkable. Routine critique belongs in conditions/dissent, NOT a
hard blocker."""


# ── Adapter helper ──────────────────────────────────────────────────────────

async def _call_adapter(
    role_name: str,
    system_prompt: str,
    user_message: str,
) -> dict:
    """Call the configured concilium LLM adapter and parse a JSON reply.

    Resolves the adapter/model from concilium's agent-settings entry (see
    agent_settings.resolve_agent) exactly like the legacy engine did, then
    invokes ``adapter.complete(..., response_format="json")``. Returns a dict;
    on any parse/transport failure returns ``{"error": str(e)}`` so callers can
    degrade gracefully instead of crashing a phase.
    """
    try:
        cfg = resolve_agent("concilium") or {}
        adapter_name = cfg.get("adapter") or "deepseek"
        model_name = cfg.get("model") or cfg.get("default_model") or "deepseek-chat"
        role_default_temp = float(COUNSELOR_ROLES.get(role_name, {}).get("temperature", 0.2))
        try:
            temperature = float(cfg.get("temperature", role_default_temp))
        except (TypeError, ValueError):
            temperature = role_default_temp

        config = AgentConfig(
            adapter=adapter_name,
            model=model_name,
            temperature=temperature,
            max_tokens=2048,
        )
        adapter = get_adapter(config)
        raw = await adapter.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            response_format="json",
        )
    except Exception as e:  # transport-level failure
        return {"error": str(e)}

    raw = (raw or "").strip()
    if not raw:
        return {"error": "empty adapter response"}
    # Direct JSON first.
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the first JSON object embedded in prose/wrapper text.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return {"error": f"unparseable response: {raw[:300]}"}


def _as_list(value: Any) -> list[str]:
    """Coerce an adapter field value into a clean list[str]."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for it in value:
            s = str(it).strip() if it is not None else ""
            if s:
                out.append(s)
        return out
    return []


def _clean_text(value: Any) -> str:
    return (str(value).strip() if value is not None else "")


# ── Consensus math ──────────────────────────────────────────────────────────

def consensus_from_verdicts(verdicts: list[Verdict]) -> Consensus:
    """Aggregate a Phase C pass into a Consensus.

    support = (n_approve + 0.5 * n_soft) / n_roles  (abstain excluded from the
    denominator so a skipped/failed role can't drag a healthy consensus down).
    Genuine hard blockers come only from roles that explicitly vote ``reject``
    with a blocker-level note — routine critique is folded into conditions so
    the ratchet ratchets instead of re-raising verbatim criticism.
    """
    cons = Consensus()
    considered = [v for v in verdicts if v.vote != Vote.ABSTAIN]
    if not considered:
        cons.reached = False
        return cons

    n_approve = 0
    n_soft = 0
    n_reject = 0
    n_abstain = len(verdicts) - len(considered)

    for v in considered:
        v_notes = [n for n in v.notes]
        if v.vote == Vote.APPROVE:
            n_approve += 1
        elif v.vote == Vote.REVISE:
            n_soft += 1
        elif v.vote == Vote.REJECT:
            n_reject += 1

        # Genuine blocker = an explicit hard blocker (reject vote carries one).
        blockers = [n for n in v_notes if n.kind == NoteKind.BLOCKER]
        if blockers and v.vote == Vote.REJECT:
            for b in blockers:
                cons.blockers.append({"role": v.role, "blocker": b.text})
        conditions = [n for n in v_notes if n.kind == NoteKind.CONDITION]
        for c in conditions:
            if c.text not in cons.conditions:
                cons.conditions.append(c.text)

    cons.n_approve = n_approve
    cons.n_revise = n_soft
    cons.n_reject = n_reject
    cons.n_abstain = n_abstain

    denom = float(max(1, len(considered)))
    support = (n_approve + 0.5 * n_soft) / denom
    cons.final_support = round(support, 4)
    cons.reached = not cons.blockers and support >= CONSENSUS_THRESHOLD
    return cons


# ── Status / event persistence ──────────────────────────────────────────────

def _session_dir(session_id: str) -> Path:
    d = CONCILIUM_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_status(
    session_id: str,
    state: str,
    current_round: int | None = None,
    max_rounds: int | None = None,
    active_roles: list[str] | None = None,
    error: str | None = None,
) -> None:
    """Atomically write STATUS.json for a Concilium session (router polls this).

    Field names (session_id/state/started_at/updated_at/current_round/max_rounds/
    active_roles/error) are read by the backend router — matched exactly.
    ``state`` is the string value ("in_progress"/"approved"/"rejected"/"escalated").
    Best-effort: a disk failure never crashes the orchestrator.
    """
    try:
        d = _session_dir(session_id)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status_path = d / "STATUS.json"

        started_at = now
        if status_path.exists():
            try:
                prior = json.loads(status_path.read_text())
                started_at = prior.get("started_at", now)
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        payload = {
            "session_id": session_id,
            "state": state,
            "started_at": started_at,
            "updated_at": now,
            "current_round": current_round,
            "max_rounds": max_rounds,
            "active_roles": active_roles or [],
        }
        if error:
            payload["error"] = str(error)[:500]
        tmp = status_path.with_suffix(".status.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(status_path)
    except OSError:
        return


def _write_event(session_id: str, event_type: str, data: dict | None = None) -> None:
    """Append one structured JSON line to the session's events.jsonl."""
    try:
        d = _session_dir(session_id)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "type": event_type,
            "data": data or {},
        }
        with open(d / "events.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        return


def _persist_result(result: "DeliberationResult") -> None:
    """Write the flat result schema to the session dir AND atomically refresh
    ``app/agents/concilium/last_result.json`` (fixes the stale-last-result bug)."""
    consensus_d = result.consensus
    payload = {
        "session_id": result.session_id,
        "status": result.status.value,
        "plan": result.plan or "",
        "conditions": list(result.conditions or []),
        "blockers": list(result.blockers or []),
        "consensus": {
            "support": getattr(consensus_d, "final_support", 0.0),
            "reached": getattr(consensus_d, "reached", False),
            "n_approve": getattr(consensus_d, "n_approve", 0),
            "n_soft": getattr(consensus_d, "n_revise", 0),
            "n_reject": getattr(consensus_d, "n_reject", 0),
            "conditions": consensus_d.conditions if consensus_d else [],
        },
        "contributing_roles": list(result.contributing_roles or []),
        "rounds_completed": len(result.rounds),
        "duration_s": result.duration_s,
        "total_cost_usd": result.total_cost_usd,
    }
    try:
        d = _session_dir(result.session_id)
        (d / "result.json").write_text(json.dumps(payload, indent=2))
    except OSError:
        pass

    # Atomically refresh last_result.json (tmp + os.replace).
    last = CONCILIUM_DIR / "last_result.json"
    try:
        tmp = last.with_suffix(".result.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(last)
    except OSError:
        return


def _notify_master(session_id: str, status: str, summary: str) -> None:
    """Push a termination notification into master's queue (best-effort).

    Mirrors the legacy notification mechanism (app/backend/services/
    notification_queue) so master sees an approved/escalated/rejected outcome on
    its next handle_task_stream turn as ``[SYSTEM NOTIFICATION ...]``. A backend
    without the queue available (e.g. unit test) simply no-ops.
    """
    try:
        from app.backend.services.notification_queue import notification_queue
    except Exception:
        return

    approved = status == "approved"
    try:
        notification_queue.enqueue(
            parent_agent="master",
            child_agent="concilium",
            status="done" if approved else "error",
            result=summary if approved else "",
            error="" if approved else summary,
            session_id=session_id,
        )
    except Exception:
        return


# ── Orchestrator ────────────────────────────────────────────────────────────

class ConciliumOrchestrator:
    """Synthesis-first Concilium orchestrator.

    Usage:
        orchestrator = ConciliumOrchestrator(session_id="abc")
        result = await orchestrator.deliberate(plan_text="...")
    """

    def __init__(
        self,
        session_id: str | None = None,
        max_rounds: int = 3,
        counselor_roles: list[str] | None = None,
    ):
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.max_rounds = int(max_rounds or 3)
        self.active_roles: list[str] = list(counselor_roles) if counselor_roles else list(COUNSELOR_ROLES.keys())
        self.rounds: int = 0                 # passes actually completed
        self._passes: list[DeliberationRound] = []
        self._result: DeliberationResult | None = None
        self._notices: list[str] = []
        self._citations: list[str] = []
        self._plan_input = ""
        self._started_mono = 0.0

    # ── Phase A: contribution ────────────────────────────────────────────────
    async def _contribute(self, plan_text: str) -> list[Contribution]:
        contributions: list[Contribution] = []
        tasks = []
        for role in self.active_roles:
            if role not in COUNSELOR_ROLES:
                continue
            cfg = COUNSELOR_ROLES[role]
            system_prompt = cfg["prompt"] + _CONTRIBUTION_CONTRACT
            tasks.append((role, system_prompt, plan_text))
        _write_event(self.session_id, "round_1", {"phase": "A_contribute", "roles": [t[0] for t in tasks]})
        _write_event(self.session_id, "contributed", {"roles": [t[0] for t in tasks]})

        import asyncio as _aio
        results = await _aio.gather(
            *[_call_adapter(role, sys_p, f"Raw task / plan under consideration:\n\n{plan_text}")
              for (role, sys_p, _) in tasks],
            return_exceptions=True,
        )
        for (role, _sys, _txt), data in zip(tasks, results):
            if isinstance(data, Exception) or not isinstance(data, dict):
                contributions.append(Contribution(role=role, raw_output=str(data)))
                continue
            if data.get("error"):
                contributions.append(Contribution(role=role, raw_output=str(data["error"])))
                continue
            contributions.append(Contribution(
                role=role,
                proposals=_as_list(data.get("proposals")),
                risks_to_watch=_as_list(data.get("risks_to_watch")),
                questions=_as_list(data.get("questions")),
                raw_output="",
            ))
        return contributions

    # ── Phase B: synthesize + converge ───────────────────────────────────────
    async def _synthesize(self, contributions: list[Contribution], base_plan: str) -> str:
        bundle: list[str] = []
        for c in contributions:
            bundle.append(f"## {c.role} contribution")
            if c.proposals:
                bundle.append("Proposals:\n" + "\n".join(f"- {p}" for p in c.proposals))
            if c.risks_to_watch:
                bundle.append("Risks to watch:\n" + "\n".join(f"- {r}" for r in c.risks_to_watch))
            if c.questions:
                bundle.append("Questions:\n" + "\n".join(f"- {q}" for q in c.questions))
            rest = c.raw_output.strip()
            if rest:
                bundle.append("Raw notes:\n" + rest)
        if not bundle:
            return base_plan or ""

        synthesizer_cfg = COUNSELOR_ROLES.get(DEFAULT_SYNTHESIZER)
        system_prompt = (synthesizer_cfg["prompt"] if synthesizer_cfg else "") + _SYNTHESIS_CONTRACT
        user_msg = (
            f"Base plan to synthesize and improve:\n\n{base_plan}\n\n"
            f"Counselor contributions to merge into ONE coherent plan body:\n\n"
            + "\n\n".join(bundle)
        )
        _write_event(self.session_id, "round_1", {"phase": "B_synthesize", "synthesizer": DEFAULT_SYNTHESIZER})
        data = await _call_adapter(DEFAULT_SYNTHESIZER, system_prompt, user_msg)
        if isinstance(data, dict) and not data.get("error"):
            plan_body = _clean_text(data.get("plan") or data.get("plan_body") or "")
            if len(plan_body) >= 40:  # accept substantive merges only
                _write_event(self.session_id, "converged", {"synthesized_len": len(plan_body)})
                return plan_body
            self._notices.append("synthesizer returned insubstantive merged plan; keeping base")
        return base_plan or ""

    async def _verify_pass(self, plan_body: str) -> tuple[list[CounselNote], Consensus]:
        """Cross-examine the merged plan across remaining roles. Returns notes + consensus."""
        notes: list[CounselNote] = []
        tasks = []
        for role in self.active_roles:
            if role == DEFAULT_SYNTHESIZER:
                continue  # the synthesizer doesn't cross-examine its own merge
            if role not in COUNSELOR_ROLES:
                continue
            cfg = COUNSELOR_ROLES[role]
            tasks.append((role, cfg["prompt"] + _VERIFY_CONTRACT))
        # at least synthesize role reviews? include synthesizer as harmless:
        # if the panel only has the synthesizer, still get one reviewer.
        if not tasks and DEFAULT_SYNTHESIZER in self.active_roles:
            tasks.append((DEFAULT_SYNTHESIZER, COUNSELOR_ROLES[DEFAULT_SYNTHESIZER]["prompt"] + _VERIFY_CONTRACT))

        import asyncio as _aio
        results = await _aio.gather(
            *[_call_adapter(role, sys_p, f"Final synthesized plan to verify:\n\n{plan_body}")
              for (role, sys_p) in tasks],
            return_exceptions=True,
        )
        verdicts: list[Verdict] = []
        for (role, _sys), data in zip(tasks, results):
            if isinstance(data, Exception) or not isinstance(data, dict):
                verdicts.append(Verdict(role=role, vote=Vote.ABSTAIN, support=0.0,
                                        notes=[], raw_output=str(data)))
                continue
            if data.get("error"):
                verdicts.append(Verdict(role=role, vote=Vote.ABSTAIN, support=0.0,
                                        notes=[], raw_output=str(data["error"])))
                continue
            vstr = _clean_text(data.get("vote")).lower()
            if vstr.startswith("approve"):
                vote = Vote.APPROVE
            elif vstr.startswith("reject"):
                vote = Vote.REJECT
            else:
                vote = Vote.REVISE  # soft approve
            hard = str(data.get("hard_blocker", "")).strip().lower() in ("1", "true", "yes")
            role_notes: list[CounselNote] = []
            # Only a genuine hard blocker (explicitly flagged + reject vote)
            # becomes a NoteKind.BLOCKER. Everything else is non-blocking.
            if hard and vote == Vote.REJECT:
                btext = _clean_text(data.get("blocker_text") or data.get("blocker") or data.get("rationale"))
                if btext:
                    role_notes.append(CounselNote(role=role, kind=NoteKind.BLOCKER, text=btext[:600]))
            for cond in _as_list(data.get("conditions")):
                role_notes.append(CounselNote(role=role, kind=NoteKind.CONDITION, text=cond[:400]))
            for dis in _as_list(data.get("dissent")):
                self._notices.append(f"[{role}] dissent: {dis[:240]}")
            verdicts.append(Verdict(role=role, vote=vote,
                                    support=float(vote == Vote.APPROVE),
                                    notes=role_notes,
                                    rationale=_clean_text(data.get("rationale"))[:400],
                                    raw_output=""))
            notes.extend(role_notes)

        cons = consensus_from_verdicts(verdicts)
        self.rounds += 1
        self._passes.append(DeliberationRound(
            pass_number=self.rounds,
            phase="C_verify",
            plan=plan_body,
            consensus=cons,
            completed_at=datetime.now(timezone.utc).isoformat(),
        ))
        return notes, cons

    # ── Public API ───────────────────────────────────────────────────────────
    async def deliberate(self, plan_text: str) -> DeliberationResult:
        self._plan_input = plan_text or ""
        self._started_mono = time.monotonic()
        base = self._plan_input
        _session_dir(self.session_id)

        # Phase A
        _write_status(self.session_id, "in_progress", current_round=0,
                      max_rounds=self.max_rounds, active_roles=self.active_roles)
        _write_event(self.session_id, "deliberation_started",
                     {"plan_length": len(base), "max_rounds": self.max_rounds,
                      "roles": self.active_roles})
        contributions = await self._contribute(base)
        contributing_roles = [c.role for c in contributions]

        # Phase B
        _write_status(self.session_id, "in_progress", current_round=1,
                      max_rounds=self.max_rounds, active_roles=self.active_roles)
        merged = await self._synthesize(contributions, base)

        # Convergence passes: re-verify the merged plan. Reconverge only while
        # budget allows and a pass materially changes nothing we already rejected.
        conditions: list[str] = []
        final_blockers: list[CounselNote] = []
        support = 0.0
        reached = False

        pass_num = 1
        while pass_num <= self.max_rounds + 1:
            _write_status(self.session_id, "in_progress", current_round=pass_num,
                          max_rounds=self.max_rounds, active_roles=self.active_roles)
            notes, cons = await self._verify_pass(merged)
            hard_blockers = [n for n in notes if n.kind == NoteKind.BLOCKER]
            conds = [_clean_text(n.text) for n in notes if n.kind == NoteKind.CONDITION and n.text]
            for c in conds:
                if c not in conditions:
                    conditions.append(c)
            support = cons.final_support
            reached = cons.reached

            # Simple stopping: no hardening blockers + threshold met => approve now.
            if reached:
                final_blockers = hard_blockers
                merged_keep = merged
                break

            # If a genuine irreconcilable blocker persists across all budget,
            # esc/blocks; but first attempt ONE reconverge to fold feedback.
            if hard_blockers:
                # Fold the first blocker's guidance into a reconverge attempt once.
                if self.rounds < self.max_rounds and merged:
                    reconverged = await self._synthesize(
                        contributions, merged  # synthesizer folds reviewer feedback on next pass
                    )
                    if reconverged and reconverged.strip() != merged.strip():
                        merged = reconverged
                        self._notices.append(f"reconverge pass {pass_num}: conflict blocker folded")
                        pass_num += 1
                        continue
                    # reconverge didn't change => genuinely irreconcilable
                final_blockers = hard_blockers
                break

            # No hard blockers but below threshold -> reconverge on remaining budget.
            if not hard_blockers and self.rounds < self.max_rounds:
                reconverged = await self._synthesize(contributions, merged)
                if reconverged and reconverged.strip() != merged.strip():
                    merged = reconverged
                    self._notices.append(f"reconverge pass {pass_num}: raised support fold")
                    pass_num += 1
                    continue
            break

        # Phase C decision
        duration = time.monotonic() - self._started_mono
        blocker_texts = list(dict.fromkeys(n.text for n in final_blockers if n.text))

        if blocker_texts:
            # genuinely irreconcilable
            status = DeliberationStatus.ESCALATED
            _write_event(self.session_id, "escalated", {"blockers": blocker_texts, "rounds": self.rounds})
            _write_status(self.session_id, "escalated", current_round=self.rounds,
                          max_rounds=self.max_rounds, active_roles=self.active_roles)
        elif reached or support >= CONSENSUS_THRESHOLD:
            status = DeliberationStatus.APPROVED
            _write_event(self.session_id, "approved", {"support": support, "rounds": self.rounds})
            _write_status(self.session_id, "approved", current_round=self.rounds,
                          max_rounds=self.max_rounds, active_roles=self.active_roles)
        else:
            # no genuine hard blocker but never cleared the threshold: best-effort
            # approve carries conditions (ratchet ran out). Escalate only would be
            # overly harsh here; mark approved-with-conditions is the ratchet result.
            status = DeliberationStatus.APPROVED
            _write_event(self.session_id, "approved", {"support": support, "rounds": self.rounds,
                                                       "note": "conditions carried"})
            _write_status(self.session_id, "approved", current_round=self.rounds,
                          max_rounds=self.max_rounds, active_roles=self.active_roles)

        result = DeliberationResult(
            status=status,
            plan=merged,
            conditions=conditions,
            blockers=blocker_texts,
            consensus=Consensus(
                n_approve=0, n_revise=0, n_reject=0, n_abstain=0,
                final_support=support,
                reached=reached or (not blocker_texts and support >= CONSENSUS_THRESHOLD),
                blockers=blocker_texts,
                conditions=conditions,
            ),
            rounds=list(self._passes),
            contributing_roles=contributing_roles,
            session_id=self.session_id,
            duration_s=duration,
            total_cost_usd=0.0,
        )
        self._result = result
        _persist_result(result)

        # Final STATUS + notification
        lines = [
            f"Concilium session {self.session_id} — {status.value.upper()}",
            f"Rounds: {self.rounds} | Duration: {duration:.1f}s",
        ]
        first = (merged or "").strip().splitlines()
        if first:
            lines.append(f"Plan: {first[0][:160]}")
        if status == DeliberationStatus.APPROVED:
            lines.append(f"Next step: implement the approved plan (see app/agents/concilium/{self.session_id}/result.json).")
        else:
            lines.append(f"Full report: app/agents/concilium/{self.session_id}/result.json")
        summary = "\n".join(lines)
        _write_event(self.session_id, "deliberation_completed", {"status": status.value,
                                                                 "rounds": self.rounds,
                                                                 "duration_s": round(duration, 3)})
        _write_status(self.session_id, status.value, current_round=self.rounds,
                      max_rounds=self.max_rounds, active_roles=self.active_roles)
        _notify_master(self.session_id, status.value, summary)
        return result


# ── Legacy heuristics preserved for app.utils.concilium_router imports ──────

def assess_complexity(task_description: str) -> int:
    """Heuristic complexity assessment (1-10) based on task description."""
    score = 1  # base
    indicators = {
        "multi-file": 2, "multiple files": 2, "several files": 1,
        "refactor": 2, "restructure": 2, "migrate": 2,
        "security": 2, "credential": 2, "secret": 2, "permission": 1,
        "config": 1, "settings": 1, ".env": 2, "database": 2,
        "new agent": 2, "new feature": 1, "architecture": 2,
        "api": 1, "endpoint": 1, "integration": 1,
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
