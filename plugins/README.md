# YAPOC Plugins

Place Python tool plugins here. Each `.py` file should define one or more
`BaseTool` subclasses. They'll be discovered and registered on startup.

## Example plugin: `plugins/hello_tool.py`

```python
from app.utils.tools import BaseTool, RiskTier

class HelloTool(BaseTool):
    name = "hello"
    description = "Says hello"
    risk_tier = RiskTier.AUTO
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Who to greet"}
        },
        "required": ["name"]
    }

    async def execute(self, name: str) -> str:
        return f"Hello, {name}!"
```

After adding a plugin, restart the server for it to be loaded.
