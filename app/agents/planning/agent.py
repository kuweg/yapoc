from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class PlanningAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "planning")


planning_agent = PlanningAgent()
