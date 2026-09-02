"""Concilium deliberate tool — a first-class TOOL that gates a task through
the Concilium deliberation engine.

Wraps the existing gate (``app.utils.concilium_router.should_deliberate``)
and, when warranted, the orchestrator (``app.utils.concilium.ConciliumOrchestrator``).
This is the clean, persistent replacement for the ad-hoc "write a temp python
script and shell_exec it" hack previously used to drive Concilium from builder.
"""

import json
from typing import Any

from app.utils.tools import BaseTool


class ConciliumDeliberateTool(BaseTool):
    name = "concilium_deliberate"
    description = (
        "Gate a task through the Concilium multi-agent deliberation engine. "
        "First evaluates the task against should_deliberate (complexity/risk/risk-flags "
        "thresholds). If below the threshold it returns status 'skipped'. Otherwise it "
        "runs ConciliumOrchestrator.deliberate() and returns a structured JSON result with "
        "status (approved|rejected|escalated), session_id, rounds_completed, cost, and "
        "either approved_plan or escalation_summary."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "The task text / plan to be reviewed. Required.",
            },
            "affected_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of files the task touches (used for risk assessment).",
            },
            "complexity": {
                "type": "integer",
                "description": "Optional integer complexity score (1-10). Derived from task_description if omitted.",
            },
            "risk": {
                "type": ["string", "integer"],
                "description": "Optional risk: an integer (1-10) or 'low' | 'moderate' | 'high'. Derived if omitted.",
            },
        },
        "required": ["task_description"],
    }

    def __init__(self, **kwargs: Any):
        # No agent_dir / sandbox wiring needed; kept a plain constructor
        # so build_tools() never hard-breaks on this tool.
        pass

    async def execute(self, **params: Any) -> str:
        task_description = (params.get("task_description") or "").strip()
        if not task_description:
            return "concilium_deliberate: task_description is required"

        # Lazy imports avoid import cycles at registry-load time.
        from app.utils.concilium_router import should_deliberate

        do_it, rationale = should_deliberate(
            complexity=params.get("complexity"),
            risk=params.get("risk"),
            flags=params.get("flags"),
            task_description=task_description,
            affected_files=params.get("affected_files"),
        )

        if not do_it:
            return json.dumps(
                {
                    "status": "skipped",
                    "reason": "below deliberation threshold",
                    "rationale": rationale,
                }
            )

        from app.utils.concilium import ConciliumOrchestrator

        result = await ConciliumOrchestrator().deliberate(plan_text=task_description)

        out = {
            "status": result.status.value,
            "session_id": result.session_id,
            "rounds_completed": len(result.rounds),
            "duration_s": result.duration_s,
            "total_cost_usd": result.total_cost_usd,
            "approved_plan": result.approved_plan,
            "escalation_summary": result.escalation_summary,
        }
        return json.dumps(out, default=str)
