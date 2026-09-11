from app.agents.base import BaseAgent
from app.utils import AGENTS_DIR


class LMStudioTestAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "lmstudio-test")


lmstudio_test_agent = LMStudioTestAgent()
