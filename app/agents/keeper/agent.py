from app.agents.base import BaseAgent
from app.utils import AGENTS_DIR


class KeeperAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "keeper")


keeper_agent = KeeperAgent()
