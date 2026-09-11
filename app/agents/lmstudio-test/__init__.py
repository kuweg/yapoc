"""Scratch agent for validating local inference through LM Studio.

The directory name contains a hyphen, so this package cannot be reached with
an ``import app.agents.lmstudio-test`` statement — use
``importlib.import_module("app.agents.lmstudio-test")``. The runner does not
need either: it constructs ``BaseAgent`` from the directory path directly.
"""

from .agent import LMStudioTestAgent, lmstudio_test_agent

__all__ = ["LMStudioTestAgent", "lmstudio_test_agent"]
