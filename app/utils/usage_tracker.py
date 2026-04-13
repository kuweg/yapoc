"""Per-agent token and cost tracking.

Each agent directory has a ``USAGE.json`` file that accumulates lifetime
token usage, tool-call counts, and USD cost broken down per model. This
lets operators answer "how much has Planning cost me this week" without
grepping logs, and gives Model Manager a data source for downgrade
recommendations.

The tracker is best-effort: every public method wraps its IO in a
try/except so a bad write never breaks the agent's main run loop.

Schema of ``USAGE.json``:

    {
      "total_input_tokens": 0,
      "total_output_tokens": 0,
      "total_cache_creation_tokens": 0,
      "total_cache_read_tokens": 0,
      "total_tool_calls": 0,
      "total_turns": 0,
      "total_cost_usd": 0.0,
      "by_model": {
        "<model_id>": {
          "input_tokens": 0,
          "output_tokens": 0,
          "cache_creation_tokens": 0,
          "cache_read_tokens": 0,
          "cost_usd": 0.0,
          "turns": 0,
          "tool_calls": 0
        }
      },
      "last_updated": "<ISO-8601 UTC>"
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.adapters.models import ALL_PRICING

log = logging.getLogger(__name__)

USAGE_FILE = "USAGE.json"


def _empty_model_bucket() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cost_usd": 0.0,
        "turns": 0,
        "tool_calls": 0,
    }


def _empty_usage() -> dict[str, Any]:
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_creation_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_tool_calls": 0,
        "total_turns": 0,
        "total_cost_usd": 0.0,
        "by_model": {},
        "last_updated": "",
    }


def _calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Compute USD cost for one turn. Mirrors ``cli.renderer.calc_cost``.

    Kept here (rather than imported) to avoid a cli→utils dependency cycle
    and to let the tracker work inside agent subprocesses that never import
    the renderer.
    """
    pricing = ALL_PRICING.get(model)
    if not pricing:
        return 0.0
    in_rate, out_rate = pricing
    base_input = max(0, input_tokens - cache_creation_tokens - cache_read_tokens)
    return (
        base_input * in_rate
        + cache_creation_tokens * in_rate * 1.25
        + cache_read_tokens * in_rate * 0.1
        + output_tokens * out_rate
    ) / 1_000_000


class UsageTracker:
    """Persistent per-agent usage counter backed by ``USAGE.json``."""

    def __init__(self, agent_dir: Path) -> None:
        self._dir = agent_dir
        self._path = agent_dir / USAGE_FILE

    # ── IO ───────────────────────────────────────────────────────────────

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return _empty_usage()
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Backfill any missing top-level keys so old files keep working
            defaults = _empty_usage()
            for k, v in defaults.items():
                data.setdefault(k, v)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("usage_tracker: unreadable %s (%s), resetting", self._path, exc)
            return _empty_usage()

    def _write(self, data: dict[str, Any]) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("usage_tracker: write failed for %s: %s", self._path, exc)

    # ── Public API ───────────────────────────────────────────────────────

    def record_turn(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Accumulate one LLM turn's usage into ``USAGE.json``.

        Called from ``BaseAgent.run_stream_with_tools`` whenever a
        ``UsageStats`` event is observed. Safe to call with zero values
        (will still bump ``total_turns`` by 1, which is the desired
        semantic for "an LLM turn happened").
        """
        try:
            data = self._read()
            bucket = data["by_model"].setdefault(model, _empty_model_bucket())

            bucket["input_tokens"] += int(input_tokens or 0)
            bucket["output_tokens"] += int(output_tokens or 0)
            bucket["cache_creation_tokens"] += int(cache_creation_tokens or 0)
            bucket["cache_read_tokens"] += int(cache_read_tokens or 0)
            bucket["turns"] += 1

            cost = _calc_cost(
                model,
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
            )
            bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)

            data["total_input_tokens"] += int(input_tokens or 0)
            data["total_output_tokens"] += int(output_tokens or 0)
            data["total_cache_creation_tokens"] += int(cache_creation_tokens or 0)
            data["total_cache_read_tokens"] += int(cache_read_tokens or 0)
            data["total_turns"] += 1
            data["total_cost_usd"] = round(data["total_cost_usd"] + cost, 6)
            data["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            self._write(data)
        except Exception as exc:  # never let tracking break the run loop
            log.warning("usage_tracker.record_turn failed: %s", exc)

    def record_tool_call(self, model: str, count: int = 1) -> None:
        """Increment the per-model and global tool-call counters.

        Called once per executed tool invocation from
        ``BaseAgent.run_stream_with_tools`` after each ``ToolDone`` event.
        The model argument is the model that issued the call, so we can
        attribute tool usage to the model that decided to use the tool.
        """
        if count <= 0:
            return
        try:
            data = self._read()
            bucket = data["by_model"].setdefault(model, _empty_model_bucket())
            bucket["tool_calls"] += int(count)
            data["total_tool_calls"] += int(count)
            data["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            self._write(data)
        except Exception as exc:
            log.warning("usage_tracker.record_tool_call failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Return the current accumulated usage (fresh read, no side effects)."""
        return self._read()

    def reset(self) -> None:
        """Wipe the file back to zero. Useful between sessions or after
        a cost-period rollover."""
        try:
            self._write(_empty_usage())
        except Exception as exc:
            log.warning("usage_tracker.reset failed: %s", exc)
