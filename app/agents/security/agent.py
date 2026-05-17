from app.agents.base import BaseAgent
from app.config import settings

AGENTS_DIR = settings.agents_dir


class SecurityAgent(BaseAgent):
    """Action classifier. Receives a proposed tool call from another agent and
    returns a JSON allow/deny decision. See PROMPT.MD for the contract.

    Security agent has no tools and cannot mutate state — it is consulted as a
    one-shot LLM call by ``security_gate.classify`` rather than spawned as a
    subprocess. This class exists so the runtime can resolve adapter/model
    config the same way it does for every other agent.
    """

    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "security")


security_agent = SecurityAgent()
