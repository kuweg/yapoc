from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class DocumentProcessorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "document_processor")


document_processor_agent = DocumentProcessorAgent()
