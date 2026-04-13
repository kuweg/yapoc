"""Doctor Agent — autonomous system health monitor.

Periodically scans all agents' HEALTH.MD, CRASH.MD, and OUTPUT.MD files,
then produces a rolling HEALTH_SUMMARY.MD report. Also detects performance
patterns, stale tasks, crashed agents, and cross-agent error patterns.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.base import BaseAgent
from app.config import settings
from app.utils.crash import count_crashes

_TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]")
_TIMEOUT_RE = re.compile(r"Task timed out", re.IGNORECASE)
_SELF_OPT_RE = re.compile(r"SELF_OPT:")
# Match common error substrings for cross-agent pattern detection
_ERROR_EXTRACT_RE = re.compile(r"ERROR:\s*(.{10,80})")


class DoctorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(settings.agents_dir / "doctor")

    # ── Log rotation ──────────────────────────────────────────────────

    def _prune_health_log(self, health_path: Path, max_age_days: int) -> None:
        """Remove HEALTH.MD entries older than *max_age_days*."""
        if not health_path.exists():
            return
        text = health_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return

        cutoff = (datetime.now() - timedelta(days=max_age_days)).date()
        kept: list[str] = []
        keep_block = True  # whether the current block (timestamped line + continuations) is kept

        for line in text.splitlines(keepends=True):
            m = _TIMESTAMP_RE.match(line)
            if m:
                line_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                keep_block = line_date >= cutoff
            # Lines without a timestamp belong to the preceding block (e.g. tracebacks)
            if keep_block:
                kept.append(line)

        health_path.write_text("".join(kept), encoding="utf-8")

    # ── Optimization suggestions ─────────────────────────────────────

    def _write_optimization_suggestions(
        self,
        agents_dir: Path,
        targets: list[tuple[str, str, int]],
    ) -> None:
        """Write optimization suggestions to target agents' HEALTH.MD.

        targets: list of (agent_name, issue_type, count)
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for agent_name, issue_type, count in targets:
            health_path = agents_dir / agent_name / "HEALTH.MD"
            if not health_path.parent.exists():
                continue

            if issue_type == "repeated_timeouts":
                suggestion = (
                    f"[{now}] WARNING: OPTIMIZATION_SUGGESTION: "
                    f"{count} timeouts detected. Consider switching to a faster model "
                    f"or increasing task_timeout in CONFIG.md.\n"
                )
            elif issue_type == "high_error_rate":
                suggestion = (
                    f"[{now}] WARNING: OPTIMIZATION_SUGGESTION: "
                    f"{count} errors detected. Consider switching to a more capable model "
                    f"or reviewing the agent's prompt and tools configuration.\n"
                )
            else:
                continue

            try:
                with open(health_path, "a", encoding="utf-8") as f:
                    f.write(suggestion)
            except OSError:
                pass

    # ── Stale task detection ─────────────────────────────────────────

    def _check_stale_tasks(
        self, agents_dir: Path, agent_dirs: list[Path],
    ) -> list[tuple[str, str]]:
        """Detect stuck or crashed-while-running tasks.

        Returns list of (agent_name, diagnostic_message) for any findings.
        """
        findings: list[tuple[str, str]] = []
        now = datetime.now(timezone.utc)
        default_timeout = settings.task_timeout  # 300s default

        for agent_dir in agent_dirs:
            name = agent_dir.name
            task_path = agent_dir / "TASK.MD"
            status_path = agent_dir / "STATUS.json"
            if not task_path.exists():
                continue

            task_text = task_path.read_text(encoding="utf-8", errors="replace")
            # Parse frontmatter
            fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", task_text, re.DOTALL)
            if not fm_match:
                continue
            fm: dict[str, str] = {}
            for line in fm_match.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()

            status = fm.get("status", "")
            if status != "running":
                continue

            # Check 1: stale running task (assigned_at too old)
            assigned_at = fm.get("assigned_at", "")
            if assigned_at:
                try:
                    assigned_dt = datetime.fromisoformat(assigned_at.replace("Z", "+00:00"))
                    elapsed = (now - assigned_dt).total_seconds()
                    stale_threshold = default_timeout * 2
                    if elapsed > stale_threshold:
                        mins = int(elapsed / 60)
                        findings.append((
                            name,
                            f"STALE_TASK: status=running for {mins}m "
                            f"(threshold: {int(stale_threshold / 60)}m). "
                            f"assigned_at={assigned_at}. Consider killing and restarting.",
                        ))
                except (ValueError, TypeError):
                    pass

            # Check 2: process terminated but task still running (crash)
            if status_path.exists():
                try:
                    sj = json.loads(status_path.read_text(encoding="utf-8"))
                    proc_state = sj.get("state", "")
                    pid = sj.get("pid")
                    if proc_state == "terminated":
                        findings.append((
                            name,
                            f"CRASHED_TASK: TASK.MD says running but STATUS.json "
                            f"says terminated (PID {pid}). Agent likely crashed "
                            f"mid-task. Check CRASH.MD or OUTPUT.MD.",
                        ))
                    elif proc_state in ("idle", "running") and pid:
                        # Verify PID is actually alive
                        try:
                            os.kill(pid, 0)
                        except (ProcessLookupError, PermissionError):
                            findings.append((
                                name,
                                f"ZOMBIE_TASK: TASK.MD says running, STATUS.json "
                                f"says {proc_state} (PID {pid}), but process is dead.",
                            ))
                except (json.JSONDecodeError, OSError):
                    pass

        return findings

    # ── Cross-agent pattern recognition ──────────────────────────────

    def _detect_cross_agent_patterns(
        self, agents_dir: Path, agent_dirs: list[Path],
    ) -> list[str]:
        """Find error messages that appear in 3+ agents' HEALTH.MD.

        Returns formatted finding strings (one per pattern detected).
        """
        # Collect error snippets per agent
        agent_errors: dict[str, list[str]] = {}
        for agent_dir in agent_dirs:
            health_path = agent_dir / "HEALTH.MD"
            if not health_path.exists():
                continue
            text = health_path.read_text(encoding="utf-8", errors="replace")
            snippets: list[str] = []
            for m in _ERROR_EXTRACT_RE.finditer(text):
                # Normalize: strip timestamps, whitespace, truncate
                snippet = m.group(1).strip()
                # Take first 50 chars as the "signature" for grouping
                sig = snippet[:50]
                snippets.append(sig)
            if snippets:
                agent_errors[agent_dir.name] = snippets

        if len(agent_errors) < 3:
            return []

        # Count how many agents share each error signature
        sig_to_agents: dict[str, list[str]] = {}
        for agent_name, snippets in agent_errors.items():
            for sig in set(snippets):  # dedupe per-agent
                sig_to_agents.setdefault(sig, []).append(agent_name)

        findings: list[str] = []
        for sig, agents in sig_to_agents.items():
            if len(agents) >= 3:
                agent_list = ", ".join(sorted(agents))
                findings.append(
                    f"CROSS_AGENT_PATTERN: {len(agents)} agents "
                    f"({agent_list}) share error: \"{sig}\""
                )

        return findings

    # ── Runaway cost detection ───────────────────────────────────────

    def _detect_runaway_agents(
        self, agents_dir: Path, agent_dirs: list[Path],
    ) -> list[tuple[str, str]]:
        """Detect agents whose cost exceeds the runaway threshold.

        Compares each agent's total_cost_usd against the median cost
        multiplied by ``settings.cost_runaway_multiplier``. Returns
        (agent_name, diagnostic_message) for flagged agents.
        """
        costs: dict[str, float] = {}
        for agent_dir in agent_dirs:
            usage_path = agent_dir / "USAGE.json"
            if not usage_path.exists():
                continue
            try:
                data = json.loads(usage_path.read_text(encoding="utf-8"))
                cost = data.get("total_cost_usd", 0.0)
                if cost > 0:
                    costs[agent_dir.name] = cost
            except (json.JSONDecodeError, OSError):
                continue

        if len(costs) < 2:
            return []

        sorted_costs = sorted(costs.values())
        mid = len(sorted_costs) // 2
        if len(sorted_costs) % 2 == 0:
            median = (sorted_costs[mid - 1] + sorted_costs[mid]) / 2
        else:
            median = sorted_costs[mid]

        if median <= 0:
            return []

        multiplier = settings.cost_runaway_multiplier
        threshold = median * multiplier
        findings: list[tuple[str, str]] = []

        for name, cost in costs.items():
            if cost > threshold:
                findings.append((
                    name,
                    f"RUNAWAY_COST: ${cost:.4f} exceeds {multiplier}x median "
                    f"(${median:.4f} median, ${threshold:.4f} threshold)",
                ))

        return findings

    # ── Health check ──────────────────────────────────────────────────

    async def run_health_check(self) -> str:
        """Scan all agents and produce a health summary report."""
        agents_dir = settings.agents_dir
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sections: list[str] = [f"# Health Summary\n\nGenerated: {now}\n"]

        agent_dirs = sorted(
            p for p in agents_dir.iterdir()
            if p.is_dir() and not p.name.startswith("_") and not p.name == "base"
        )

        # Prune old entries from all agents' HEALTH.MD first
        retention = settings.health_log_retention_days
        for agent_dir in agent_dirs:
            self._prune_health_log(agent_dir / "HEALTH.MD", retention)

        issues_found = 0
        optimization_targets: list[tuple[str, str, int]] = []

        for agent_dir in agent_dirs:
            name = agent_dir.name
            agent_section: list[str] = []

            # Check HEALTH.MD
            health_path = agent_dir / "HEALTH.MD"
            if health_path.exists():
                health_text = health_path.read_text(encoding="utf-8", errors="replace").strip()
                if health_text:
                    lines = health_text.splitlines()
                    error_lines = [
                        l for l in lines
                        if "ERROR:" in l or "DENIED" in l
                    ]
                    warning_lines = [
                        l for l in lines
                        if "WARNING:" in l
                    ]
                    self_opt_lines = [
                        l for l in lines
                        if _SELF_OPT_RE.search(l)
                    ]
                    timeout_lines = [
                        l for l in lines
                        if _TIMEOUT_RE.search(l)
                    ]
                    if error_lines:
                        issues_found += len(error_lines)
                        agent_section.append(f"  - HEALTH.MD: {len(error_lines)} error(s)")
                        for line in error_lines[-3:]:
                            agent_section.append(f"    - {line.strip()[:200]}")
                    if warning_lines:
                        agent_section.append(f"  - HEALTH.MD: {len(warning_lines)} warning(s)")
                        for line in warning_lines[-3:]:
                            agent_section.append(f"    - {line.strip()[:200]}")
                    if self_opt_lines:
                        agent_section.append(f"  - HEALTH.MD: {len(self_opt_lines)} self-optimization event(s)")
                        for line in self_opt_lines[-3:]:
                            agent_section.append(f"    - {line.strip()[:200]}")
                    # Track timeouts for optimization suggestions
                    if len(timeout_lines) >= 3:
                        optimization_targets.append((name, "repeated_timeouts", len(timeout_lines)))
                    if len(error_lines) >= 5:
                        optimization_targets.append((name, "high_error_rate", len(error_lines)))

            # Check CRASH.MD
            crash_path = agent_dir / "CRASH.MD"
            crash_count = count_crashes(crash_path)
            if crash_count > 0:
                issues_found += crash_count
                agent_section.append(f"  - CRASH.MD: {crash_count} crash(es)")

            # Check SERVER_CRASH.MD (master only)
            server_crash = agent_dir / "SERVER_CRASH.MD"
            server_crashes = count_crashes(server_crash)
            if server_crashes > 0:
                issues_found += server_crashes
                agent_section.append(f"  - SERVER_CRASH.MD: {server_crashes} crash(es)")

            if agent_section:
                sections.append(f"## {name}\n" + "\n".join(agent_section))
            else:
                sections.append(f"## {name}\n  - OK")

        # ── Stale task detection (M5A) ──
        stale_findings = self._check_stale_tasks(agents_dir, agent_dirs)
        if stale_findings:
            stale_section = ["## Stale / Crashed Tasks\n"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            for agent_name, diag in stale_findings:
                stale_section.append(f"  - **{agent_name}**: {diag}")
                issues_found += 1
                # Write warning to the affected agent's HEALTH.MD
                health_path = agents_dir / agent_name / "HEALTH.MD"
                try:
                    with open(health_path, "a", encoding="utf-8") as f:
                        f.write(f"[{now_str}] WARNING: {diag}\n")
                except OSError:
                    pass
                # Also notify master
                master_health = agents_dir / "master" / "HEALTH.MD"
                try:
                    with open(master_health, "a", encoding="utf-8") as f:
                        f.write(f"[{now_str}] WARNING: [doctor] {agent_name}: {diag}\n")
                except OSError:
                    pass
            sections.append("\n".join(stale_section))

        # ── Cross-agent pattern recognition (M5B) ──
        cross_patterns = self._detect_cross_agent_patterns(agents_dir, agent_dirs)
        if cross_patterns:
            pattern_section = ["## Cross-Agent Error Patterns\n"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            for finding in cross_patterns:
                pattern_section.append(f"  - {finding}")
                issues_found += 1
                # Write to master's HEALTH.MD
                master_health = agents_dir / "master" / "HEALTH.MD"
                try:
                    with open(master_health, "a", encoding="utf-8") as f:
                        f.write(f"[{now_str}] WARNING: [doctor] {finding}\n")
                except OSError:
                    pass
            sections.append("\n".join(pattern_section))

        # ── Runaway cost detection (M9D) ──
        runaway_findings = self._detect_runaway_agents(agents_dir, agent_dirs)
        if runaway_findings:
            runaway_section = ["## Runaway Cost Alerts\n"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            for agent_name, diag in runaway_findings:
                runaway_section.append(f"  - **{agent_name}**: {diag}")
                issues_found += 1
                # Write to master's HEALTH.MD
                master_health = agents_dir / "master" / "HEALTH.MD"
                try:
                    with open(master_health, "a", encoding="utf-8") as f:
                        f.write(f"[{now_str}] WARNING: [doctor] {agent_name}: {diag}\n")
                except OSError:
                    pass
            sections.append("\n".join(runaway_section))

        # Summary line
        status = "ISSUES DETECTED" if issues_found > 0 else "ALL CLEAR"
        sections.insert(1, f"**Status:** {status} ({issues_found} issue(s) across {len(agent_dirs)} agents)\n")

        report = "\n\n".join(sections) + "\n"

        # Write optimization suggestions to target agents' HEALTH.MD
        self._write_optimization_suggestions(agents_dir, optimization_targets)

        # Write to HEALTH_SUMMARY.MD
        summary_path = self._dir / "HEALTH_SUMMARY.MD"
        summary_path.write_text(report, encoding="utf-8")

        # Log to own memory
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        await self._append_file(
            "MEMORY.MD",
            f"[{timestamp}] health_check: {status} — {issues_found} issue(s)\n",
        )

        return report


doctor_agent = DoctorAgent()
