# Project Managing — Master Agent Knowledge Base

This file contains operational knowledge for managing the YAPOC project itself.
Use this as a reference when the task involves running, stopping, restarting the system,
or managing dependencies and the Python environment.

---

## Environment

- **Python**: 3.12+
- **Package manager**: Poetry (uses `pyproject.toml` + `poetry.lock`)
- **Virtual environment**: managed by Poetry, activate with `poetry shell` or prefix commands with `poetry run`
- **Config**: `.env` file in project root — never commit secrets, always load via `python-dotenv`

---

## Starting the System

### Full system start (recommended)
```bash
poetry run yapoc start
```

### Backend only (FastAPI + uvicorn)
```bash
poetry run uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8000
```
- `--reload` enables hot-reload on file changes (dev only, remove in production)
- Default port: **8000**

### Verify it's running
```bash
poetry run yapoc ping
# or
curl http://localhost:8000/health
```

---

## Stopping the System

### Via CLI
```bash
poetry run yapoc stop
```

### Manual (if CLI is unavailable)
Find and kill the uvicorn process:
```bash
lsof -i :8000          # find PID on port 8000
kill <PID>             # graceful stop
kill -9 <PID>          # force stop if graceful fails
```

---

## Restarting

### Via CLI
```bash
poetry run yapoc restart
```

### Manual
Stop then start (see above). Always prefer graceful stop — agents flush their MEMORY.MD on shutdown.

---

## Dependency Management (Poetry)

### Install all dependencies (after clone or pyproject.toml change)
```bash
poetry install
```

### Add a new runtime dependency
```bash
poetry add <package>
poetry add <package>@^2.0        # with version constraint
poetry add <package> --group dev  # dev-only dependency
```

After adding, `pyproject.toml` and `poetry.lock` are both updated automatically.

### Remove a dependency
```bash
poetry remove <package>
```

### Update dependencies
```bash
poetry update            # update all within constraints
poetry update <package>  # update one package
```

### Show installed packages
```bash
poetry show              # all packages
poetry show <package>    # details of one package
poetry show --outdated   # packages with available updates
```

### Check for conflicts or issues
```bash
poetry check
```

### Export requirements (if needed for Docker or CI)
```bash
poetry export -f requirements.txt --output requirements.txt --without-hashes
```

---

## Project Version

Version is defined in `pyproject.toml` under `[project] version`.
Bump it manually or via:
```bash
poetry version patch   # 0.1.0 → 0.1.1
poetry version minor   # 0.1.0 → 0.2.0
poetry version major   # 0.1.0 → 1.0.0
```

---

## Running Tests

```bash
poetry run pytest                        # all tests
poetry run pytest tests/                 # specific directory
poetry run pytest tests/test_master.py   # specific file
poetry run pytest -v                     # verbose output
poetry run pytest -k "test_name"         # filter by name
```

---

## Useful Dev Commands

### Check code style (if linter is configured)
```bash
poetry run ruff check .
poetry run ruff format .
```

### Inspect current environment
```bash
poetry env info          # Python path, venv location
poetry env list          # all envs for this project
```

### Open a Python shell inside the env
```bash
poetry run python
# or after `poetry shell`:
python
```

---

## Agent File Management

Agents store their state in markdown files. When managing agents directly:

| File | When to touch |
|---|---|
| `PROMPT.MD` | Changing agent role/behaviour (requires restart of that agent) |
| `TASK.MD` | Assigning a new task — write here, agent picks it up automatically |
| `MEMORY.MD` | Append new key events; do not delete existing entries arbitrarily |
| `NOTES.MD` | Update `[config]` block to change model/adapter; hot-reloads without restart |
| `HEALTH.MD` | Read to diagnose; append fixes after resolving an error |

Agent directories live at: `app/agents/<agent_name>/`

### Reassign an agent's model without restart
Edit `app/agents/<agent_name>/NOTES.MD`, update the `[config]` block:
```markdown
[config]
adapter: anthropic
model: claude-opus-4-6
temperature: 0.2
```
The runner watches for changes and hot-reloads.

---

## Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Port 8000 already in use | Previous instance didn't stop | `lsof -i :8000` → `kill <PID>` |
| `ModuleNotFoundError` | Running outside Poetry env | Prefix with `poetry run` or activate with `poetry shell` |
| `poetry install` fails | Lock file out of sync | `poetry lock --no-update` then retry |
| Agent not picking up new task | `TASK.MD` is not empty from previous run | Clear the file and re-write the task |
| `.env` values not loaded | File missing or wrong location | Must be in project root (`yapoc/.env`) |
