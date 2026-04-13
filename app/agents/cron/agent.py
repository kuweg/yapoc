from app.agents.base import BaseAgent
from app.utils import AGENTS_DIR


class CronAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "cron")


cron_agent = CronAgent()
