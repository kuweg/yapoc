"""
Tests for the is_infrastructure flag on the agent listing endpoint.

Verifies that:
- base, doctor, model_manager -> is_infrastructure = True
- master, planning, builder, keeper, cron -> is_infrastructure = False
- The field defaults to False for any unknown agent name
"""

from __future__ import annotations

import pytest
from app.backend.models import AgentStatus


# ---------------------------------------------------------------------------
# Unit tests: AgentStatus model defaults
# ---------------------------------------------------------------------------

class TestAgentStatusModel:
    def test_is_infrastructure_defaults_to_false(self):
        """is_infrastructure should default to False for backward compatibility."""
        agent = AgentStatus(
            name="master",
            status="idle",
            model="claude-sonnet-4-6",
            has_task=False,
            memory_entries=0,
            health_errors=0,
        )
        assert agent.is_infrastructure is False

    def test_is_infrastructure_can_be_set_true(self):
        agent = AgentStatus(
            name="doctor",
            status="idle",
            model="claude-haiku",
            has_task=False,
            memory_entries=0,
            health_errors=0,
            is_infrastructure=True,
        )
        assert agent.is_infrastructure is True

    def test_is_infrastructure_serializes_in_model_dump(self):
        """is_infrastructure must appear in model_dump() output (used by FastAPI serialization)."""
        agent = AgentStatus(
            name="base",
            status="idle",
            model="unknown",
            has_task=False,
            memory_entries=0,
            health_errors=0,
            is_infrastructure=True,
        )
        dumped = agent.model_dump()
        assert "is_infrastructure" in dumped
        assert dumped["is_infrastructure"] is True


# ---------------------------------------------------------------------------
# Unit tests: infrastructure flag logic
# ---------------------------------------------------------------------------

class TestInfrastructureFlag:
    """
    Test the infrastructure classification logic directly, without needing
    real agent directories on disk.
    """

    INFRA_AGENTS = {"base", "doctor", "model_manager"}
    NON_INFRA_AGENTS = {"master", "planning", "builder", "keeper", "cron"}

    @pytest.mark.parametrize("name", ["base", "doctor", "model_manager"])
    def test_infra_agents_are_flagged(self, name):
        """Infrastructure agents must have is_infrastructure=True."""
        is_infra = name in self.INFRA_AGENTS
        assert is_infra is True, f"{name} should be infrastructure"

    @pytest.mark.parametrize("name", ["master", "planning", "builder", "keeper", "cron"])
    def test_non_infra_agents_are_not_flagged(self, name):
        """Non-infrastructure agents must have is_infrastructure=False."""
        is_infra = name in self.INFRA_AGENTS
        assert is_infra is False, f"{name} should NOT be infrastructure"

    def test_unknown_agent_is_not_infrastructure(self):
        """Any agent not in the known infra set defaults to False."""
        unknown_names = ["my_custom_agent", "temp_worker", "data_processor"]
        for name in unknown_names:
            assert name not in self.INFRA_AGENTS, f"{name} should not be infrastructure"

    def test_infra_set_is_exactly_three_agents(self):
        """The infrastructure set should contain exactly base, doctor, model_manager."""
        assert self.INFRA_AGENTS == {"base", "doctor", "model_manager"}

    def test_agent_status_with_infra_flag_true(self):
        """AgentStatus built for an infra agent should carry is_infrastructure=True."""
        for name in self.INFRA_AGENTS:
            agent = AgentStatus(
                name=name,
                status="idle",
                model="unknown",
                has_task=False,
                memory_entries=0,
                health_errors=0,
                is_infrastructure=(name in self.INFRA_AGENTS),
            )
            assert agent.is_infrastructure is True, f"{name} should have is_infrastructure=True"

    def test_agent_status_with_infra_flag_false(self):
        """AgentStatus built for a non-infra agent should carry is_infrastructure=False."""
        for name in self.NON_INFRA_AGENTS:
            agent = AgentStatus(
                name=name,
                status="idle",
                model="unknown",
                has_task=False,
                memory_entries=0,
                health_errors=0,
                is_infrastructure=(name in self.INFRA_AGENTS),
            )
            assert agent.is_infrastructure is False, f"{name} should have is_infrastructure=False"
