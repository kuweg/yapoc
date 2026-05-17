from typing import Any
from datetime import datetime

from app.utils.tools import BaseTool


class WeekdayTool(BaseTool):
    name = "weekday"
    description = "Return today's weekday as a lowercase English name."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        return datetime.now().strftime("%A").lower()
