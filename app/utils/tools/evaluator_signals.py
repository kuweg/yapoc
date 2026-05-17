"""Evaluator-only tool — surfaces recent system-performance signals.

Wraps the existing ``/metrics/observability`` endpoint and joins it with each
agent's effective config (adapter, model, temperature, fallback chain) so the
evaluator's LLM context contains *both* runtime behavior and configuration in
a single JSON document.

Used exclusively by the Evaluator Agent (see ``app/agents/evaluator/``).
Registered as ``get_recent_signals`` in ``app/utils/tools/__init__.py``.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings

from . import BaseTool


class GetRecentSignalsTool(BaseTool):
    name = "get_recent_signals"
    description = (
        "Return recent system performance signals for self-evaluation. "
        "Pulls the unified observability snapshot (per-agent cost/tokens/error "
        "counts, recent errors feed, recent tasks feed) PLUS each agent's "
        "configured adapter/model/fallback chain. The evaluator agent uses "
        "this single call to identify regressions and propose config or "
        "prompt changes. Returns JSON-formatted text — read it carefully "
        "before proposing any change, every proposal must be rooted in this "
        "data."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "top_n_tasks": {
                "type": "integer",
                "description": (
                    "Maximum number of recent tasks to include in the "
                    "recent_tasks feed (default 50, max 200)."
                ),
                "default": 50,
            },
        },
    }

    async def execute(self, **params: Any) -> str:
        try:
            top_n_tasks = int(params.get("top_n_tasks", 50))
        except (TypeError, ValueError):
            top_n_tasks = 50
        top_n_tasks = max(1, min(top_n_tasks, 200))

        # ── Observability snapshot from the local backend ───────────────
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.base_url}/metrics/observability"
                )
                resp.raise_for_status()
                obs = resp.json()
        except Exception as exc:
            return f"ERROR: get_recent_signals failed to fetch observability: {exc}"

        # Trim recent_tasks to caller's preference
        if isinstance(obs, dict) and "recent_tasks" in obs:
            obs["recent_tasks"] = obs["recent_tasks"][:top_n_tasks]

        # ── Per-agent config snapshot (adapter/model/fallbacks) ─────────
        agent_configs: dict[str, Any] = {}
        try:
            from app.utils.agent_settings import resolve_agent

            for agent_row in obs.get("agents", []) if isinstance(obs, dict) else []:
                name = agent_row.get("name")
                if not name:
                    continue
                cfg = resolve_agent(name)
                if cfg is None:
                    agent_configs[name] = {"note": "no agent-settings.json entry"}
                    continue
                agent_configs[name] = {
                    "adapter": cfg.get("adapter"),
                    "model": cfg.get("model"),
                    "temperature": cfg.get("temperature"),
                    "max_tokens": cfg.get("max_tokens"),
                    "fallback_models": [
                        f"{f.get('adapter')}/{f.get('model')}"
                        for f in (cfg.get("fallbacks") or [])
                    ],
                }
        except Exception as exc:
            agent_configs = {"_error": f"resolve_agent failed: {exc}"}

        # ── Sandbox forbidden-paths per agent (for proposing changes) ──
        # The evaluator needs to know what each agent can/can't touch when
        # suggesting tweaks. Pull a compact summary from CONFIG.yaml.
        sandbox_summary: dict[str, Any] = {}
        try:
            import re

            agents_dir = settings.agents_dir
            for agent_row in obs.get("agents", []) if isinstance(obs, dict) else []:
                name = agent_row.get("name")
                if not name:
                    continue
                cfg_path = agents_dir / name / "CONFIG.yaml"
                if not cfg_path.exists():
                    continue
                text = cfg_path.read_text(encoding="utf-8", errors="ignore")
                # Crude scan for sandbox.forbidden: lines under it
                forbidden: list[str] = []
                in_block = False
                in_forbidden = False
                for raw in text.splitlines():
                    s = raw.strip()
                    if s == "sandbox:":
                        in_block = True
                        continue
                    if in_block:
                        if s.startswith("forbidden:"):
                            in_forbidden = True
                            continue
                        if in_forbidden:
                            m = re.match(r"\s+-\s+(.+?)\s*$", raw)
                            if m:
                                forbidden.append(m.group(1).strip())
                                continue
                            if s and not s.startswith("#"):
                                in_forbidden = False
                        if s and not raw.startswith(" ") and not s.startswith("#"):
                            in_block = False
                if forbidden:
                    sandbox_summary[name] = forbidden
        except Exception:
            pass

        payload = {
            "observability": obs,
            "agent_configs": agent_configs,
            "agent_sandboxes": sandbox_summary,
        }

        # JSON dump. The evaluator's prompt asks the model to read this
        # carefully and ground every proposal in specific entries here.
        return json.dumps(payload, indent=2)
