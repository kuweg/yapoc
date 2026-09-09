import json
from typing import Any

from . import BaseTool


class RenderCalendarTool(BaseTool):
    name = "render_calendar"
    description = (
        "Render a calendar block in the chat. Pass a list of events (each with "
        "summary, start, end, optional location/description) and an optional "
        "week_start (RFC3339/ISO date) to anchor the week grid. Returns JSON with "
        "the validated events for the frontend to render as a calendar."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "description": "List of calendar events to display (may be empty).",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Short title/summary of the event.",
                        },
                        "start": {
                            "type": "string",
                            "description": "Event start time (RFC3339 or ISO datetime).",
                        },
                        "end": {
                            "type": "string",
                            "description": "Event end time (RFC3339 or ISO datetime).",
                        },
                        "location": {
                            "type": "string",
                            "description": "Optional event location.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional event description.",
                        },
                    },
                    "required": ["summary", "start", "end"],
                },
            },
            "week_start": {
                "type": "string",
                "description": "Optional anchor date for the week grid (RFC3339 or ISO date).",
            },
        },
        "required": ["events"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            events = params.get("events")
            if not isinstance(events, list):
                return "ERROR: events must be a list of objects"

            for idx, event in enumerate(events):
                if not isinstance(event, dict):
                    return f"ERROR: events[{idx}] must be an object"
                summary = event.get("summary")
                start = event.get("start")
                end = event.get("end")
                if not isinstance(summary, str) or not summary.strip():
                    return f"ERROR: events[{idx}].summary must be a non-empty string"
                if not isinstance(start, str) or not start.strip():
                    return f"ERROR: events[{idx}].start must be a non-empty string"
                if not isinstance(end, str) or not end.strip():
                    return f"ERROR: events[{idx}].end must be a non-empty string"

            return json.dumps(
                {
                    "type": "calendar",
                    "events": events,
                    "week_start": params.get("week_start"),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"ERROR: {exc}"
