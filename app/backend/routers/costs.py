"""Costs router — per-task cost records aggregated across all agents.

Endpoints:
  GET /api/costs          — all cost records, sorted by timestamp desc
                            optional: ?agent=<name>  filter by agent
                            optional: ?limit=100     max records returned
  GET /api/costs/summary  — per-agent totals
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/costs")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CostRecord(BaseModel):
    task_id:     str
    description: str
    agent_name:  str
    tokens_in:   int
    tokens_out:  int
    cost_usd:    float
    timestamp:   str
    model_used:  str


class AgentCostSummary(BaseModel):
    agent_name:      str
    total_cost_usd:  float
    total_tasks:     int
    total_tokens_in: int
    total_tokens_out: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_all() -> list[dict]:
    """Load all COSTS.json records from all agent directories."""
    try:
        from app.utils.cost_tracker import load_all_costs
        return load_all_costs(settings.agents_dir)
    except Exception:
        return []


def _to_record(raw: dict) -> CostRecord:
    return CostRecord(
        task_id=raw.get("task_id", ""),
        description=raw.get("description", ""),
        agent_name=raw.get("agent_name", ""),
        tokens_in=int(raw.get("tokens_in", 0)),
        tokens_out=int(raw.get("tokens_out", 0)),
        cost_usd=float(raw.get("cost_usd", 0.0)),
        timestamp=raw.get("timestamp", ""),
        model_used=raw.get("model_used", ""),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CostRecord])
async def list_costs(
    agent: Optional[str] = Query(default=None, description="Filter by agent name"),
    limit: int = Query(default=100, ge=1, le=10000, description="Max records to return"),
):
    """Return cost records across all agents, sorted by timestamp descending.

    Optional query params:
    - ``agent``: filter to a single agent name
    - ``limit``: max number of records (default 100, max 10000)
    """
    records = _load_all()

    if agent:
        records = [r for r in records if r.get("agent_name") == agent]

    # Already sorted desc by load_all_costs; apply limit
    records = records[:limit]

    return [_to_record(r) for r in records]


@router.get("/summary", response_model=list[AgentCostSummary])
async def cost_summary():
    """Return per-agent cost totals.

    Returns a list of AgentCostSummary objects, one per agent that has
    at least one cost record, sorted by total_cost_usd descending.
    """
    records = _load_all()

    # Aggregate by agent_name
    agg: dict[str, dict] = {}
    for r in records:
        name = r.get("agent_name", "unknown")
        if name not in agg:
            agg[name] = {
                "agent_name":       name,
                "total_cost_usd":   0.0,
                "total_tasks":      0,
                "total_tokens_in":  0,
                "total_tokens_out": 0,
            }
        agg[name]["total_cost_usd"]   += float(r.get("cost_usd", 0.0))
        agg[name]["total_tasks"]      += 1
        agg[name]["total_tokens_in"]  += int(r.get("tokens_in", 0))
        agg[name]["total_tokens_out"] += int(r.get("tokens_out", 0))

    # Round cost totals
    for v in agg.values():
        v["total_cost_usd"] = round(v["total_cost_usd"], 6)

    summaries = sorted(agg.values(), key=lambda x: x["total_cost_usd"], reverse=True)
    return [AgentCostSummary(**s) for s in summaries]
