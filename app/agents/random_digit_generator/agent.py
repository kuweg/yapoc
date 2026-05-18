from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class RandomDigitGeneratorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "random_digit_generator")


random_digit_generator_agent = RandomDigitGeneratorAgent()
