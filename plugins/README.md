# YAPOC Plugins

Drop Python files here. Each `.py` file defines one or more `BaseTool`
subclasses; they're discovered and registered in `TOOL_REGISTRY` at startup,
or on demand via the admin reload endpoint (see below).

## Plugin shape

A plugin tool is a subclass of `BaseTool` from `app.utils.tools`. Required
class attributes: `name` (the registry key, also what agents call), a
human-readable `description`, and `input_schema` (JSON Schema describing
the call args). Implement async `execute(**params)` returning a string.

`plugins/hello_tool.py`:

```python
from typing import Any

from app.utils.tools import BaseTool


class HelloTool(BaseTool):
    name = "hello"
    description = "Say hello to the named person."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Who to greet.",
            },
        },
        "required": ["name"],
    }

    async def execute(self, **params: Any) -> str:
        name = params.get("name", "world")
        return f"Hello, {name}!"
```

After dropping the file in `plugins/`, either restart the server or hit the
reload endpoint (below). Then add `"hello"` to any agent's `CONFIG.yaml`
`tools:` list to make it callable from that agent.

## Hot reload — no restart

```
curl -X POST http://localhost:8000/admin/plugins/reload \
  -H "Authorization: Bearer $WEBHOOK_SECRET"
```

The endpoint requires the same `webhook_secret` configured for
`/webhook/task`. Response:

```json
{
  "status": "ok",
  "plugins_loaded": 1,
  "plugin_tool_names": ["hello"],
  "added": ["hello"],
  "removed": [],
  "total_tools": 39
}
```

Subsequent reloads pick up file edits — the loader drops cached plugin
modules from `sys.modules` before re-importing.

## Rules

- Filenames starting with `_` are skipped.
- A plugin cannot shadow a core tool: if `name` collides with an existing
  registry key from the core tool set, the plugin is skipped with a warning.
- If a previously-loaded plugin file is removed before a reload, its tools
  are unregistered.
- Plugin tools run with the same permissions as core tools — there is no
  sandbox between them. Audit plugin code the same way you'd audit a PR
  to `app/utils/tools/`.

## Authoring tips

- Keep `execute` async — the tool loop awaits it. For CPU-bound work, use
  `await asyncio.to_thread(...)` so you don't block the event loop.
- Validate inputs explicitly; pydantic isn't applied to `**params`.
- Return a string. The runtime stringifies non-strings, but explicit is
  clearer in logs.
- Errors should be returned as `"ERROR: <reason>"` strings — raising
  bubbles up through the tool-call loop and the agent has to handle it.
