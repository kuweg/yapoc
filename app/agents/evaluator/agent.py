from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class EvaluatorAgent(BaseAgent):
    """Meta-cognition agent. Reviews recent YAPOC performance and writes
    a human-reviewable proposals report — see PROMPT.MD for the contract.

    No special methods: master invokes this agent via the standard
    spawn_agent → BaseAgent.run_stream_with_tools path. The agent's
    behavior is fully expressed in its PROMPT.MD + CONFIG.yaml + the
    get_recent_signals tool.
    """

    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "evaluator")


evaluator_agent = EvaluatorAgent()
