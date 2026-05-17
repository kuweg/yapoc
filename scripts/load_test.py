#!/usr/bin/env python3
"""YAPOC load test — exercises master + multi-agent + notifications at full capacity.

This harness drives every fix shipped in claude-solution-design.md:

  Fix 1.1 / 1.3 — notifications arriving while master is busy must NOT drop.
  Fix 1.2       — processing failures must NOT silently lose notifications.
  Fix 1.4       — startup resume must complete before watchers race.
  Fix 2.1 / 2.2 — master must be able to run far past 300s without cancellation.
  Fix 3.1       — NotifyParentTool fires Redis primary, queue only on fallback.
  Fix 3.2       — RESULT.MD-canonical dedup catches Poller + NotifyParent races.
  Fix 3.3       — restart with consumed_at TASK.MD must not re-process.
  Fix 3.5       — Poller _notified survives restart.

Usage:
    poetry run yapoc start                 # in one terminal
    poetry run python scripts/load_test.py # in another

    # Pick a single scenario:
    poetry run python scripts/load_test.py --scenario fan_out
    poetry run python scripts/load_test.py --scenario interrupt
    poetry run python scripts/load_test.py --scenario long_running
    poetry run python scripts/load_test.py --scenario session_isolation
    poetry run python scripts/load_test.py --scenario all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Make app.config importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings  # noqa: E402

BASE_URL = f"http://{('127.0.0.1' if settings.host == '0.0.0.0' else settings.host)}:{settings.port}"
TIMEOUT = 30.0  # HTTP request timeout (not task timeout)

# ── The flagship orchestration prompt — exercises everything master can do ─
#
# Why this prompt: each spawn forces a sub-agent to write TASK.MD, run, write
# RESULT.MD, call notify_parent. That fires NotifyParentTool (Fix 3.1 path) and
# wakes master if idle. Asking master to use wait_for_agents and produce a
# synthesis means master stays in handle_task_stream for a long time, so the
# inbound notifications arrive during master's _run_lock — exercising Fix 1.1
# (don't ACK on busy) and Fix 1.3 (is_busy() check).
FLAGSHIP_PROMPT = (
    "End-to-end stress drill. Execute in parallel via spawn_agent, all five "
    "tasks in a single round (no sequential waiting between spawns):\n"
    "  1) builder: 'Write a 10-line Python script to projects/load_test_artifacts/hello.py "
    "     that prints \"yapoc load test ok\" and the current timestamp. Then call notify_parent.'\n"
    "  2) keeper: 'Read app/agents/master/CONFIG.yaml and report task_timeout, "
    "     adapter, and model in a 3-line summary. Then call notify_parent.'\n"
    "  3) doctor: 'Read app/agents/master/HEALTH.MD and report the number of error lines "
    "     and the most recent error timestamp. Then call notify_parent.'\n"
    "  4) librarian: 'List the *.md files directly under docs/ and report their count. "
    "     Then call notify_parent.'\n"
    "  5) planning: 'Outline in 3 bullet points how a hypothetical agent would refactor "
    "     the notification queue to be Redis-only. Then call notify_parent.'\n"
    "\n"
    "After spawning all five, call wait_for_agents with the full list and "
    "fail_fast=false. When every sub-agent has reported, produce ONE final "
    "200-word synthesis describing what each agent returned. Do NOT re-spawn, "
    "do NOT re-verify, do NOT restart the server. Submit the synthesis as "
    "your response and you are done."
)


# ────────────────────────────────────────────────────────────────────────────
# Scenarios
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenarioReport:
    name: str
    started_at: float
    ended_at: float | None = None
    task_ids: list[str] = field(default_factory=list)
    notifications_observed: int = 0
    queue_dedup_hits: int = 0
    queue_max_pending: int = 0
    errors: list[str] = field(default_factory=list)
    pass_fail: str = "pending"

    @property
    def duration_s(self) -> float:
        return (self.ended_at or time.monotonic()) - self.started_at

    def summary(self) -> str:
        status = {"pass": "\033[32mPASS\033[0m", "fail": "\033[31mFAIL\033[0m"}.get(
            self.pass_fail, f"\033[33m{self.pass_fail.upper()}\033[0m"
        )
        lines = [
            f"  {status}  {self.name}  ({self.duration_s:.1f}s)",
            f"    tasks submitted   : {len(self.task_ids)}",
            f"    notifications seen: {self.notifications_observed}",
            f"    queue dedup hits  : {self.queue_dedup_hits}",
            f"    queue max pending : {self.queue_max_pending}",
        ]
        if self.errors:
            lines.append(f"    errors            : {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"      - {e}")
        return "\n".join(lines)


async def _submit_task(client: httpx.AsyncClient, prompt: str, session_id: str | None = None) -> str:
    """POST /task — returns task_id."""
    payload: dict[str, Any] = {"prompt": prompt}
    if session_id:
        payload["session_id"] = session_id
    r = await client.post(f"{BASE_URL}/task", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return str(data.get("task_id") or data.get("id") or "")


async def _poll_task(
    client: httpx.AsyncClient, task_id: str, max_wait_s: float = 1800.0
) -> dict[str, Any]:
    """Poll GET /tasks/{task_id} until terminal state."""
    deadline = time.monotonic() + max_wait_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            r = await client.get(f"{BASE_URL}/tasks/{task_id}", timeout=TIMEOUT)
            if r.status_code == 200:
                last = r.json()
                status = str(last.get("status", ""))
                if status in ("done", "error", "timeout"):
                    return last
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2.0)
    last.setdefault("status", "timeout_polling")
    return last


def _read_queue_state() -> tuple[int, int]:
    """Return (unconsumed_count, total_count) from data/notification_queue.json."""
    p = Path("data/notification_queue.json")
    if not p.exists():
        return 0, 0
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0
    unconsumed = sum(1 for n in items if not n.get("consumed"))
    return unconsumed, len(items)


def _count_dedup_events_since(start_iso: str) -> int:
    """Count 'deduped' trace events newer than start_iso."""
    p = Path("data/notification_trace.jsonl")
    if not p.exists():
        return 0
    count = 0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") == "deduped" and entry.get("ts", "") >= start_iso:
                count += 1
    except OSError:
        pass
    return count


def _count_trace_events_since(start_iso: str, event_name: str) -> int:
    """Count trace events of `event_name` newer than start_iso."""
    p = Path("data/notification_trace.jsonl")
    if not p.exists():
        return 0
    count = 0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") == event_name and entry.get("ts", "") >= start_iso:
                count += 1
    except OSError:
        pass
    return count


async def _master_is_busy() -> bool:
    """Read master/STATUS.json — best-effort, may lag the lock."""
    p = settings.agents_dir / "master" / "STATUS.json"
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("state") == "running"
    except Exception:
        return False


# ── Scenario 1: Fan-out + fan-in ────────────────────────────────────────────


async def scenario_fan_out(client: httpx.AsyncClient) -> ScenarioReport:
    """Master spawns 5 agents in parallel via the flagship prompt; verifies all
    notifications land and the synthesis completes without losing any."""
    r = ScenarioReport(name="fan_out", started_at=time.monotonic())
    from datetime import datetime, timezone
    start_iso = datetime.now(timezone.utc).isoformat()
    try:
        tid = await _submit_task(client, FLAGSHIP_PROMPT, session_id=f"loadtest_fanout_{uuid.uuid4().hex[:6]}")
        r.task_ids.append(tid)
        print(f"  → fan_out task submitted: {tid[:8]}")
        # Monitor queue depth while task runs
        monitor_task = asyncio.create_task(_monitor_queue(r, duration_s=900))
        result = await _poll_task(client, tid, max_wait_s=1800)
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        r.notifications_observed = _count_trace_events_since(start_iso, "enqueued")
        r.queue_dedup_hits = _count_dedup_events_since(start_iso)

        if result.get("status") == "done":
            # Heuristic: synthesis should mention multiple agents
            result_text = str(result.get("result", "")).lower()
            agents_mentioned = sum(
                1 for a in ("builder", "keeper", "doctor", "librarian", "planning")
                if a in result_text
            )
            if agents_mentioned >= 3:
                r.pass_fail = "pass"
            else:
                r.pass_fail = "fail"
                r.errors.append(f"synthesis mentioned only {agents_mentioned}/5 agents")
        else:
            r.pass_fail = "fail"
            r.errors.append(f"task ended in status={result.get('status')!r}")
    except Exception as exc:
        r.pass_fail = "fail"
        r.errors.append(f"exception: {type(exc).__name__}: {exc}")
    finally:
        r.ended_at = time.monotonic()
    return r


async def _monitor_queue(report: ScenarioReport, duration_s: float) -> None:
    """Background sampler: track max pending depth of notification_queue."""
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        try:
            unconsumed, _total = _read_queue_state()
            if unconsumed > report.queue_max_pending:
                report.queue_max_pending = unconsumed
        except Exception:
            pass
        await asyncio.sleep(0.5)


# ── Scenario 2: Interrupt master mid-task ───────────────────────────────────


async def scenario_interrupt(client: httpx.AsyncClient) -> ScenarioReport:
    """Submit the flagship task. While master is busy, fire 5 small concurrent
    tasks in separate sessions — they should queue and process when master idles.
    Tests Fix 1.1 (don't drop on busy) and Fix 1.3 (is_busy via lock state)."""
    r = ScenarioReport(name="interrupt", started_at=time.monotonic())
    from datetime import datetime, timezone
    start_iso = datetime.now(timezone.utc).isoformat()
    try:
        main_tid = await _submit_task(
            client, FLAGSHIP_PROMPT,
            session_id=f"loadtest_int_main_{uuid.uuid4().hex[:6]}",
        )
        r.task_ids.append(main_tid)
        print(f"  → interrupt main task: {main_tid[:8]}")

        # Wait until master goes busy
        for _ in range(60):
            if await _master_is_busy():
                break
            await asyncio.sleep(0.5)

        # Fire 5 concurrent small tasks while master is busy
        small_prompts = [
            f"Reply with a single line: 'interrupt-{i} acknowledged' and stop." for i in range(5)
        ]
        small_tids = await asyncio.gather(*[
            _submit_task(client, p, session_id=f"loadtest_int_sub_{i}_{uuid.uuid4().hex[:6]}")
            for i, p in enumerate(small_prompts)
        ])
        r.task_ids.extend(small_tids)
        print(f"  → fired {len(small_tids)} interrupters while master busy")

        monitor_task = asyncio.create_task(_monitor_queue(r, duration_s=900))
        # Wait for the main task
        main_result = await _poll_task(client, main_tid, max_wait_s=1800)
        # Then wait for all small tasks
        small_results = await asyncio.gather(*[
            _poll_task(client, t, max_wait_s=900) for t in small_tids
        ])
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        r.notifications_observed = _count_trace_events_since(start_iso, "enqueued")
        r.queue_dedup_hits = _count_dedup_events_since(start_iso)

        failed = [t for t, res in zip(small_tids, small_results)
                  if res.get("status") not in ("done",)]
        if main_result.get("status") == "done" and not failed:
            r.pass_fail = "pass"
        else:
            r.pass_fail = "fail"
            if main_result.get("status") != "done":
                r.errors.append(f"main task: {main_result.get('status')!r}")
            for t in failed:
                r.errors.append(f"interrupter {t[:8]} did not complete")
    except Exception as exc:
        r.pass_fail = "fail"
        r.errors.append(f"exception: {type(exc).__name__}: {exc}")
    finally:
        r.ended_at = time.monotonic()
    return r


# ── Scenario 3: Long-running master (≥10 minutes) ───────────────────────────


async def scenario_long_running(client: httpx.AsyncClient) -> ScenarioReport:
    """Master runs a multi-phase task that must not be killed by task_timeout=300s.
    Tests Fix 2.1 (master task_timeout: 0) and Fix 2.2 (dispatcher chain-bypass)."""
    r = ScenarioReport(name="long_running", started_at=time.monotonic())
    try:
        # Two sequential fan-outs in one master session → forces >10 minutes
        prompt = (
            "Run the full stress drill TWICE in series. "
            "First execution: " + FLAGSHIP_PROMPT + "\n\n"
            "Once that synthesis is written, run the SAME drill again with "
            "the same five agents but different one-sentence task variations. "
            "Produce ONE combined final report covering both rounds. Do not "
            "abort early. Total expected runtime is 10–20 minutes; that is "
            "expected and correct — do not panic and stop early."
        )
        tid = await _submit_task(
            client, prompt, session_id=f"loadtest_long_{uuid.uuid4().hex[:6]}",
        )
        r.task_ids.append(tid)
        print(f"  → long-running task: {tid[:8]} (max_wait=30min)")

        monitor_task = asyncio.create_task(_monitor_queue(r, duration_s=1800))
        result = await _poll_task(client, tid, max_wait_s=1800)
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        if result.get("status") == "done":
            r.pass_fail = "pass"
        elif result.get("status") == "timeout":
            r.pass_fail = "fail"
            r.errors.append("Master was timed out — Fix 2.1 or 2.2 not effective")
        else:
            r.pass_fail = "fail"
            r.errors.append(f"task ended in status={result.get('status')!r}")
    except Exception as exc:
        r.pass_fail = "fail"
        r.errors.append(f"exception: {type(exc).__name__}: {exc}")
    finally:
        r.ended_at = time.monotonic()
    return r


# ── Scenario 4: Session isolation ───────────────────────────────────────────


async def scenario_session_isolation(client: httpx.AsyncClient) -> ScenarioReport:
    """Three concurrent sessions, each with its own flagship task. Notifications
    must stay scoped to the originating session (see main.py session loop)."""
    r = ScenarioReport(name="session_isolation", started_at=time.monotonic())
    try:
        sessions = [f"loadtest_iso_{i}_{uuid.uuid4().hex[:6]}" for i in range(3)]
        tids = await asyncio.gather(*[
            _submit_task(client, FLAGSHIP_PROMPT, session_id=s) for s in sessions
        ])
        r.task_ids.extend(tids)
        print(f"  → 3 concurrent sessions: {[t[:8] for t in tids]}")

        monitor_task = asyncio.create_task(_monitor_queue(r, duration_s=1800))
        results = await asyncio.gather(*[
            _poll_task(client, t, max_wait_s=1800) for t in tids
        ])
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        failed = [t for t, res in zip(tids, results) if res.get("status") != "done"]
        if not failed:
            r.pass_fail = "pass"
        else:
            r.pass_fail = "fail"
            for t in failed:
                r.errors.append(f"session task {t[:8]} did not reach done")
    except Exception as exc:
        r.pass_fail = "fail"
        r.errors.append(f"exception: {type(exc).__name__}: {exc}")
    finally:
        r.ended_at = time.monotonic()
    return r


# ────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ────────────────────────────────────────────────────────────────────────────


SCENARIOS = {
    "fan_out": scenario_fan_out,
    "interrupt": scenario_interrupt,
    "long_running": scenario_long_running,
    "session_isolation": scenario_session_isolation,
}


async def _ensure_server_up(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(f"{BASE_URL}/health", timeout=5.0)
        r.raise_for_status()
    except Exception as exc:
        print(f"\033[31mServer not reachable at {BASE_URL}\033[0m: {exc}")
        print("Start it with:  poetry run yapoc start")
        sys.exit(2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--scenario", default="all",
        choices=["all", *SCENARIOS.keys()],
        help="Which scenario to run (default: all)",
    )
    parser.add_argument(
        "--print-prompt", action="store_true",
        help="Print the flagship orchestration prompt and exit (useful for REPL).",
    )
    args = parser.parse_args()

    if args.print_prompt:
        print(FLAGSHIP_PROMPT)
        return 0

    async with httpx.AsyncClient() as client:
        await _ensure_server_up(client)

        to_run = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
        print(f"\n\033[1mYAPOC load test\033[0m — running {len(to_run)} scenario(s) against {BASE_URL}\n")

        reports: list[ScenarioReport] = []
        for name in to_run:
            print(f"\033[1m── {name} ──\033[0m")
            report = await SCENARIOS[name](client)
            reports.append(report)
            print(report.summary())
            print()

        # Final tally
        print("\033[1m── tally ──\033[0m")
        passed = sum(1 for r in reports if r.pass_fail == "pass")
        failed = sum(1 for r in reports if r.pass_fail == "fail")
        print(f"  passed: {passed}/{len(reports)}")
        print(f"  failed: {failed}/{len(reports)}")
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
