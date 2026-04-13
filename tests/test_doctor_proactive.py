"""Tests for M5 — Doctor agent stale task detection and cross-agent pattern recognition."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.doctor.agent import DoctorAgent


def _make_agent_dir(base: Path, name: str, **files: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, content in files.items():
        (d / fname).write_text(content, encoding="utf-8")
    return d


def _make_frontmatter(status="running", assigned_at="", assigned_by="master"):
    return (
        f"---\nstatus: {status}\nassigned_by: {assigned_by}\n"
        f"assigned_at: {assigned_at}\n---\n\n## Task\nDo something\n"
    )


def _make_status_json(state="running", pid=99999):
    return json.dumps({"state": state, "pid": pid})


class TestStaleTaskDetection:
    def test_detects_stale_running_task(self, tmp_path):
        # Task assigned 20 minutes ago, default timeout is 300s → threshold = 600s = 10 min
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agent_dir = _make_agent_dir(
            tmp_path, "builder",
            **{"TASK.MD": _make_frontmatter(status="running", assigned_at=old_time)}
        )
        doctor = DoctorAgent.__new__(DoctorAgent)
        findings = doctor._check_stale_tasks(tmp_path, [agent_dir])
        assert len(findings) == 1
        assert "STALE_TASK" in findings[0][1]
        assert "builder" == findings[0][0]

    def test_ignores_recent_running_task(self, tmp_path):
        # Task assigned 1 minute ago — well within threshold
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agent_dir = _make_agent_dir(
            tmp_path, "builder",
            **{"TASK.MD": _make_frontmatter(status="running", assigned_at=recent)}
        )
        doctor = DoctorAgent.__new__(DoctorAgent)
        findings = doctor._check_stale_tasks(tmp_path, [agent_dir])
        assert len(findings) == 0

    def test_ignores_done_task(self, tmp_path):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agent_dir = _make_agent_dir(
            tmp_path, "builder",
            **{"TASK.MD": _make_frontmatter(status="done", assigned_at=old_time)}
        )
        doctor = DoctorAgent.__new__(DoctorAgent)
        findings = doctor._check_stale_tasks(tmp_path, [agent_dir])
        assert len(findings) == 0

    def test_detects_crashed_agent(self, tmp_path):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agent_dir = _make_agent_dir(
            tmp_path, "builder",
            **{
                "TASK.MD": _make_frontmatter(status="running", assigned_at=recent),
                "STATUS.json": _make_status_json(state="terminated", pid=12345),
            }
        )
        doctor = DoctorAgent.__new__(DoctorAgent)
        findings = doctor._check_stale_tasks(tmp_path, [agent_dir])
        assert len(findings) == 1
        assert "CRASHED_TASK" in findings[0][1]

    def test_detects_zombie_process(self, tmp_path):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Use PID 1 which exists but isn't the agent, or use a definitely-dead PID
        agent_dir = _make_agent_dir(
            tmp_path, "builder",
            **{
                "TASK.MD": _make_frontmatter(status="running", assigned_at=recent),
                "STATUS.json": _make_status_json(state="running", pid=999999999),
            }
        )
        doctor = DoctorAgent.__new__(DoctorAgent)
        findings = doctor._check_stale_tasks(tmp_path, [agent_dir])
        assert len(findings) == 1
        assert "ZOMBIE_TASK" in findings[0][1]


class TestCrossAgentPatterns:
    def test_detects_shared_error_across_3_agents(self, tmp_path):
        common_error = "[2026-04-12 10:00] ERROR: Connection refused 127.0.0.1:8000\n"
        for name in ["builder", "planning", "keeper"]:
            _make_agent_dir(tmp_path, name, **{"HEALTH.MD": common_error})

        doctor = DoctorAgent.__new__(DoctorAgent)
        agent_dirs = [tmp_path / n for n in ["builder", "planning", "keeper"]]
        findings = doctor._detect_cross_agent_patterns(tmp_path, agent_dirs)
        assert len(findings) >= 1
        assert "CROSS_AGENT_PATTERN" in findings[0]
        assert "3 agents" in findings[0]

    def test_ignores_error_in_fewer_than_3_agents(self, tmp_path):
        error = "[2026-04-12 10:00] ERROR: Something went wrong here\n"
        _make_agent_dir(tmp_path, "builder", **{"HEALTH.MD": error})
        _make_agent_dir(tmp_path, "planning", **{"HEALTH.MD": error})
        _make_agent_dir(tmp_path, "keeper", **{"HEALTH.MD": ""})  # no error

        doctor = DoctorAgent.__new__(DoctorAgent)
        agent_dirs = [tmp_path / n for n in ["builder", "planning", "keeper"]]
        findings = doctor._detect_cross_agent_patterns(tmp_path, agent_dirs)
        assert len(findings) == 0

    def test_different_errors_not_grouped(self, tmp_path):
        _make_agent_dir(tmp_path, "builder", **{"HEALTH.MD": "[2026-04-12 10:00] ERROR: Connection refused\n"})
        _make_agent_dir(tmp_path, "planning", **{"HEALTH.MD": "[2026-04-12 10:00] ERROR: File not found xyz\n"})
        _make_agent_dir(tmp_path, "keeper", **{"HEALTH.MD": "[2026-04-12 10:00] ERROR: Permission denied abc\n"})

        doctor = DoctorAgent.__new__(DoctorAgent)
        agent_dirs = [tmp_path / n for n in ["builder", "planning", "keeper"]]
        findings = doctor._detect_cross_agent_patterns(tmp_path, agent_dirs)
        assert len(findings) == 0

    def test_handles_missing_health_files(self, tmp_path):
        _make_agent_dir(tmp_path, "builder")  # no HEALTH.MD
        _make_agent_dir(tmp_path, "planning")
        _make_agent_dir(tmp_path, "keeper")

        doctor = DoctorAgent.__new__(DoctorAgent)
        agent_dirs = [tmp_path / n for n in ["builder", "planning", "keeper"]]
        findings = doctor._detect_cross_agent_patterns(tmp_path, agent_dirs)
        assert len(findings) == 0
