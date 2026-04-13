from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class BuilderAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "builder")


builder_agent = BuilderAgent()
