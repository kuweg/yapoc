import copy
import json
from typing import Any

from . import BaseTool


class RenderChartTool(BaseTool):
    name = "render_chart"
    description = (
        "Render an interactive ECharts chart in the chat. Pass a valid ECharts "
        "option object (series, xAxis, yAxis, title, tooltip, legend, etc.). "
        "Returns the normalized option JSON for the frontend to render."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "option": {
                "type": "object",
                "description": (
                    "ECharts option object (see https://echarts.apache.org/en/option.html). "
                    "Must contain at least a `series` array."
                ),
            },
        },
        "required": ["option"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            option = params.get("option")
            if not isinstance(option, dict):
                return "ERROR: option must be an object"

            series = option.get("series")

            # A single series passed as a dict is fine — wrap it below.
            if series is None or not (
                isinstance(series, list) and len(series) > 0 or isinstance(series, dict)
            ):
                return "ERROR: option must contain a non-empty 'series' array"

            # Deep-copy so we never mutate the caller's dict.
            normalized = copy.deepcopy(option)

            # Ensure series is a non-empty list (wrap a single dict if passed).
            if isinstance(normalized.get("series"), dict):
                normalized["series"] = [normalized["series"]]
            if not isinstance(normalized["series"], list) or len(normalized["series"]) == 0:
                return "ERROR: option must contain a non-empty 'series' array"

            # Render instantly, no animation glitches on first paint.
            normalized["animation"] = False

            return json.dumps(normalized, ensure_ascii=False)
        except Exception as exc:
            return f"ERROR: {exc}"
