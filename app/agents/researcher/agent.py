from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class ResearcherAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "researcher")


researcher_agent = ResearcherAgent()
