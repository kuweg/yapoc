from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class WeatherTestAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "weather_test")


weather_test_agent = WeatherTestAgent()
