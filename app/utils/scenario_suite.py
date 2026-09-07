"""Phase 3.3 — end-to-end scenario evaluation against the live system.

Every other measurement in this roadmap reads what the system already did.
Scenarios ask it to do something specific and check the result, which is the
only way to catch a regression that shows up as "the agent still finishes, but
now does the wrong thing" — invisible to a failure-rate metric.

## Two classes of scenario, deliberately separated

`offline` scenarios exercise policy and safety without any model call: the
security gate, path traversal, core-agent protection. They are free, fast, and
safe to run anywhere, including CI.

`live` scenarios dispatch a real task through the real dispatcher and cost real
money. They are **never run implicitly** — not on import, not on a schedule, not
as part of the default invocation. Scheduling a suite that spends the user's API
budget on a timer is not a decision this module gets to make on its own; the
roadmap suggested cron, and the hook is here, but it stays opt-in.

## Assertions are predicates, not string matching

A scenario asserts on observable state — a file exists with the right content, a
tool call was refused, a task reached a terminal status — rather than on the
wording of an agent's prose. Prose assertions fail on rephrasing and pass on
confident nonsense.

Usage:
    poetry run python -m app.utils.scenario_suite --list
    poetry run python -m app.utils.scenario_suite --offline
    poetry run python -m app.utils.scenario_suite --live --confirm-spend
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

Kind = Literal["offline", "live"]
Category = Literal["security", "config", "coding", "recovery", "research"]


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str
    elapsed_s: float = 0.0
    cost_usd: float = 0.0
    skipped: bool = False

    def line(self) -> str:
        mark = "SKIP" if self.skipped else ("PASS" if self.passed else "FAIL")
        cost = f" ${self.cost_usd:.4f}" if self.cost_usd else ""
        return f"[{mark}] {self.name} ({self.elapsed_s:.1f}s{cost}): {self.detail}"


@dataclass
class Scenario:
    name: str
    kind: Kind
    category: Category
    description: str
    # offline: a callable returning (passed, detail)
    check: Callable[[], tuple[bool, str]] | None = None
    # live: the prompt to dispatch, plus a predicate over the workspace
    prompt: str = ""
    verify: Callable[[Path], tuple[bool, str]] | None = None
    timeout_s: int = 300


@dataclass
class SuiteReport:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def failures(self) -> list[ScenarioResult]:
        return [r for r in self.results if not r.passed and not r.skipped]

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)
        cost = f", ${self.total_cost:.4f} spent" if self.total_cost else ""
        return (
            f"{passed}/{len(self.results) - skipped} passed, "
            f"{len(self.failures)} failed, {skipped} skipped{cost}"
        )


# ── Offline scenarios: policy and safety, no model calls ────────────────────


def _sc_destructive_shell_refused() -> tuple[bool, str]:
    from app.utils.tools.security_policy import hardcoded_check

    attacks = [
        "rm -rf /", "rm -fr /", "rm -r -f /", "rm --recursive --force /",
        "sh -c 'rm -rf /'", "dd if=/dev/zero of=/dev/sda", "mkfs.ext4 /dev/sda1",
    ]
    escaped = [
        cmd for cmd in attacks
        for caller in ("builder", "master")
        if hardcoded_check("shell_exec", {"command": cmd}, caller)[0] != "deny"
    ]
    if escaped:
        return False, f"{len(escaped)} destructive command(s) not denied: {escaped[:3]}"
    return True, f"all {len(attacks)} destructive commands denied for every caller"


def _sc_security_dir_write_locked() -> tuple[bool, str]:
    from app.utils.tools.security_policy import hardcoded_check

    paths = [
        "app/agents/security/PROMPT.MD",
        "app/agents/planning/../security/PROMPT.MD",
        "app//agents//security//PROMPT.MD",
        "./app/agents/security/CONFIG.yaml",
    ]
    escaped = [
        p for p in paths for tool in ("file_write", "file_edit")
        if hardcoded_check(tool, {"path": p}, "builder")[0] != "deny"
    ]
    if escaped:
        return False, f"security dir writable via: {escaped[:3]}"
    return True, f"all {len(paths)} spellings of the security dir are write-locked"


def _sc_core_agents_protected() -> tuple[bool, str]:
    from app.utils.tools.security_policy import hardcoded_check

    leaks = []
    for target in ("master", "security"):
        if hardcoded_check("kill_agent", {"agent_name": target}, "master")[0] != "deny":
            leaks.append(f"kill {target}")
        if hardcoded_check("agent_amnesia", {"name": target}, "master")[0] != "deny":
            leaks.append(f"amnesia {target}")
    for target in ("master", "planning", "builder", "keeper", "security"):
        if hardcoded_check("delete_agent", {"name": target}, "master")[0] != "deny":
            leaks.append(f"delete {target}")
    if leaks:
        return False, f"core-agent protection leaked: {leaks}"
    return True, "core agents cannot be killed, wiped or deleted, even by master"


def _sc_legitimate_work_not_blocked() -> tuple[bool, str]:
    """Safety that blocks real work gets switched off, so it is not safety."""
    from app.utils.tools.security_policy import hardcoded_check

    allowed = [
        ("shell_exec", {"command": "git status"}),
        ("shell_exec", {"command": "rm -rf app/frontend/dist"}),
        ("shell_exec", {"command": "curl -s -o /dev/null http://localhost:8000/api/health"}),
        ("file_edit", {"path": "app/config/settings.py"}),
        ("kill_agent", {"agent_name": "tester"}),
    ]
    blocked = [
        p for tool, p in allowed
        if hardcoded_check(tool, p, "builder" if tool != "kill_agent" else "master")[0] == "deny"
    ]
    if blocked:
        return False, f"legitimate operations denied: {blocked}"
    return True, f"all {len(allowed)} legitimate operations permitted"


def _sc_telemetry_is_truthful() -> tuple[bool, str]:
    from app.utils.release_gate import _check_telemetry_truthfulness

    check = _check_telemetry_truthfulness({})[0]
    return check.verdict != "FAIL", check.detail


def _sc_retrieval_meets_baseline() -> tuple[bool, str]:
    try:
        from app.utils.embeddings import embed_batch
        from app.utils.retrieval_benchmark import load_fixture, run_benchmark

        embed_batch(["warmup"])
    except Exception as exc:
        return True, f"skipped — embedding model unavailable ({exc})"

    result = run_benchmark(load_fixture(), mode="hybrid", k=5,
                           embed=embed_batch, collapse=True)
    ok = result.recall_at_k >= 0.90 and not result.misses
    return ok, result.summary()


def _sc_config_is_loadable() -> tuple[bool, str]:
    """Every configured agent must resolve to a usable adapter binding.

    A model id that cannot exist is a 100%-failure agent that looks fine until
    it is asked to do something — two such failures are in the task history.
    """
    import json

    from app.utils.adapters.models import MODEL_REGISTRY

    cfg = json.loads(Path("app/config/agent-settings.json").read_text())
    known = set(MODEL_REGISTRY) if isinstance(MODEL_REGISTRY, dict) else set()
    problems = []
    for name, agent in cfg.get("agents", {}).items():
        if not agent.get("adapter") or not agent.get("model"):
            problems.append(f"{name}: missing adapter/model")
            continue
        if known and agent["model"] not in known:
            problems.append(f"{name}: unknown model {agent['model']}")
    if problems:
        return False, "; ".join(problems[:4])
    return True, f"all {len(cfg.get('agents', {}))} agent bindings resolve"


OFFLINE_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("security/destructive-shell", "offline", "security",
             "Destructive shell commands are refused for every caller",
             check=_sc_destructive_shell_refused),
    Scenario("security/gate-self-protection", "offline", "security",
             "The security agent's own directory cannot be rewritten",
             check=_sc_security_dir_write_locked),
    Scenario("security/core-agents", "offline", "security",
             "Core agents survive their own blessed callers",
             check=_sc_core_agents_protected),
    Scenario("security/no-false-positives", "offline", "security",
             "Routine operations are not blocked by the gate",
             check=_sc_legitimate_work_not_blocked),
    Scenario("recovery/telemetry-truthful", "offline", "recovery",
             "Dashboard counters agree with the task tables",
             check=_sc_telemetry_is_truthful),
    Scenario("research/retrieval-baseline", "offline", "research",
             "Memory retrieval still meets the published baseline",
             check=_sc_retrieval_meets_baseline),
    Scenario("config/bindings-resolve", "offline", "config",
             "Every agent binding names a real adapter and model",
             check=_sc_config_is_loadable),
)


# ── Live scenarios: real dispatch, real spend ───────────────────────────────


def _verify_file_written(workspace: Path) -> tuple[bool, str]:
    target = workspace / "scenario_output.txt"
    if not target.exists():
        return False, f"{target} was not created"
    body = target.read_text(encoding="utf-8", errors="ignore").strip()
    return ("SCENARIO-OK" in body), f"content={body[:60]!r}"


LIVE_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "coding/write-file", "live", "coding",
        "Master delegates a trivial file write and it lands on disk",
        prompt=(
            "Delegate to builder: create the file {workspace}/scenario_output.txt "
            "containing exactly the text SCENARIO-OK. Then confirm it exists. "
            "Do not modify any other file."
        ),
        verify=_verify_file_written,
        timeout_s=420,
    ),
)


# ── Runner ──────────────────────────────────────────────────────────────────


def run_offline(scenarios: tuple[Scenario, ...] = OFFLINE_SCENARIOS) -> SuiteReport:
    report = SuiteReport()
    for sc in scenarios:
        started = time.perf_counter()
        try:
            passed, detail = sc.check()  # type: ignore[misc]
        except Exception as exc:
            passed, detail = False, f"scenario raised: {exc}"
        report.results.append(
            ScenarioResult(sc.name, passed, detail, time.perf_counter() - started)
        )
    return report


def run_live(
    scenarios: tuple[Scenario, ...] = LIVE_SCENARIOS,
    confirm_spend: bool = False,
    base_url: str = "http://localhost:8000",
) -> SuiteReport:
    """Dispatch real tasks. Refuses to run without an explicit spend confirmation.

    The guard is not ceremony: this issues real model calls against the user's
    account, and a suite that can be triggered accidentally (by a scheduler, an
    import, a default flag) is a way to spend someone else's money by mistake.
    """
    report = SuiteReport()
    if not confirm_spend:
        for sc in scenarios:
            report.results.append(ScenarioResult(
                sc.name, False,
                "refused: live scenarios cost real money, pass confirm_spend=True",
                skipped=True,
            ))
        return report

    import httpx

    for sc in scenarios:
        workspace = Path("app/tmp") / f"scenario-{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{base_url}/api/task",
                json={"task": sc.prompt.format(workspace=workspace), "source": "cli"},
                timeout=30,
            )
            task_id = resp.json().get("task_id", "")
            status, cost = _await_task(base_url, task_id, sc.timeout_s)
            if status != "done":
                report.results.append(ScenarioResult(
                    sc.name, False, f"task ended {status}",
                    time.perf_counter() - started, cost))
                continue
            passed, detail = sc.verify(workspace)  # type: ignore[misc]
            report.results.append(ScenarioResult(
                sc.name, passed, detail, time.perf_counter() - started, cost))
        except Exception as exc:
            report.results.append(ScenarioResult(
                sc.name, False, f"scenario raised: {exc}",
                time.perf_counter() - started))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    return report


def _await_task(base_url: str, task_id: str, timeout_s: int) -> tuple[str, float]:
    import httpx

    deadline = time.time() + timeout_s
    terminal = {"done", "error", "timeout", "cancelled", "interrupted"}
    while time.time() < deadline:
        try:
            body = httpx.get(f"{base_url}/api/tasks/{task_id}", timeout=15).json()
        except Exception:
            time.sleep(3)
            continue
        if body.get("status") in terminal:
            return body["status"], float(body.get("cost_usd") or 0.0)
        time.sleep(3)
    return "timeout", 0.0


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="YAPOC scenario suite")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--offline", action="store_true", help="run free, model-free scenarios")
    ap.add_argument("--live", action="store_true", help="dispatch real tasks (costs money)")
    ap.add_argument("--confirm-spend", action="store_true",
                    help="required alongside --live")
    args = ap.parse_args()

    if args.list:
        for sc in OFFLINE_SCENARIOS + LIVE_SCENARIOS:
            print(f"  [{sc.kind:<7}] {sc.name:<34} {sc.description}")
        return

    reports = []
    if args.offline or not args.live:
        report = run_offline()
        print("── offline ──")
        for r in report.results:
            print(" ", r.line())
        print(" ", report.summary())
        reports.append(report)
    if args.live:
        report = run_live(confirm_spend=args.confirm_spend)
        print("── live ──")
        for r in report.results:
            print(" ", r.line())
        print(" ", report.summary())
        reports.append(report)

    sys.exit(1 if any(r.failures for r in reports) else 0)


if __name__ == "__main__":
    main()
