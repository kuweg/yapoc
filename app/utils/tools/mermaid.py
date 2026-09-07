import json
import re
from typing import Any

from . import BaseTool

# Diagram types mermaid can render. Anything else is rejected up front so we
# never hand an arbitrary blob to the renderer.
ALLOWED_TYPES = {
    "flowchart", "flowchart-v2", "sequenceDiagram", "classDiagram",
    "stateDiagram", "stateDiagram-v2", "erDiagram", "journey",
    "gantt", "pie", "quadrantChart", "requirementDiagram", "gitGraph",
    "C4Context", "mindmap", "timeline", "zenuml", "sankey-beta",
    "xychart-beta", "block-beta", "packet-beta", "architecture-beta", "kanban",
}

MAX_SOURCE_CHARS = 20000

# Reject obvious HTML/script injection payloads up front. Mermaid's own strict
# securityLevel sanitizes rendered output, but we refuse obvious payloads too.
_DANGEROUS = re.compile(
    r"(<script|</script|javascript:|onerror=|onclick=|onload=|vbscript:|data:text/html|iframe)",
    re.IGNORECASE,
)


class RenderMermaidTool(BaseTool):
    name = "render_mermaid"
    description = (
        "Render a Mermaid diagram in the chat. Pass the full Mermaid source "
        "(e.g. 'flowchart TD\\n  A-->B'). Returns JSON with the validated "
        "source for the frontend to render as an SVG diagram."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Mermaid diagram definition source text.",
            },
        },
        "required": ["source"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            source = params.get("source")
            if not isinstance(source, str) or not source.strip():
                return "ERROR: source must be a non-empty string"
            if len(source) > MAX_SOURCE_CHARS:
                return f"ERROR: source exceeds {MAX_SOURCE_CHARS} characters"
            if _DANGEROUS.search(source):
                return "ERROR: source contains disallowed content (script/html injection is not permitted)"

            # Find the first non-comment line (skip leading %% comments).
            first_line = ""
            for line in source.strip().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("%%"):
                    continue
                first_line = stripped
                break
            dtype = first_line.split()[0] if first_line.split() else ""
            if dtype not in ALLOWED_TYPES:
                return (
                    f"ERROR: unsupported or unrecognized diagram type '{dtype}'. "
                    f"Supported: {', '.join(sorted(ALLOWED_TYPES))}"
                )

            return json.dumps(
                {"type": "mermaid", "source": source, "diagram_type": dtype},
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"ERROR: {exc}"
