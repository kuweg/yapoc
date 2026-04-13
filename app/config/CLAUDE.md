# app/config — Centralized Settings

Single file: `settings.py`. Everything reads from here.

## Access pattern
```python
from app.config import settings   # always — never os.environ
```
`get_settings()` is `@lru_cache` — one instance for the process lifetime.

## Key fields
| Field | Env var | Default |
|---|---|---|
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | `""` |
| `openai_api_key` | `OPENAI_API_KEY` | `""` |
| `openrouter_api_key` | `OPENROUTER_API_KEY` | `""` |
| `default_adapter` | `DEFAULT_ADAPTER` | `"anthropic"` |
| `default_model` | `DEFAULT_MODEL` | `"claude-sonnet-4-6"` |
| `safety_mode` | `SAFETY_MODE` | `"interactive"` |
| `context_compact_model` | — | `"claude-haiku-4-5-20251001"` |
| `doctor_interval_minutes` | — | `5` |
| `model_manager_interval_hours` | — | `24` |

## Computed properties (not env vars)
- `project_root` — derived from `settings.py` file location (not CWD)
- `agents_dir` — `project_root / "app" / "agents"`
- `base_url` — always `http://localhost:{port}` (ignores `host` binding, which is intentional)

## Gotchas
- `extra="ignore"` — typos in env var names are silently ignored (this caused the `ANTROPIC_API_KEY` bug)
- `safety_mode` only affects CLI approval gate; HTTP `/task/stream` has no gate regardless
- `agent_idle_timeout` (300s) is how long a runner subprocess stays alive before self-terminating
