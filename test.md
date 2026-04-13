# Test Plan — P1 + P2 (Autonomous Agents + CLI Polish)

## Prerequisites

```bash
poetry install
poetry run yapoc start   # backend must be running for integration tests
```

---

## Group 1: Context Assembly

### T1.1 — PROMPT.MD always included
1. `poetry run python -c "import asyncio; from app.agents.base.context import build_system_context; from app.config import settings; ctx = asyncio.run(build_system_context(settings.agents_dir / 'master')); assert 'Master Agent' in ctx; print('PASS')"`
2. Expected: `PASS`

### T1.2 — MEMORY.MD tail included
1. Write 60 lines to master's MEMORY.MD: `for i in range(60): ...`
2. Build context, verify only last 50 lines appear (default `context_memory_limit`)
3. Verify section header `## Recent Memory` is present

```python
import asyncio, pathlib
from app.agents.base.context import build_system_context
from app.config import settings

async def test():
    d = settings.agents_dir / "master"
    orig = (d / "MEMORY.MD").read_text()
    try:
        (d / "MEMORY.MD").write_text("\n".join(f"[2026-01-{i:02d}] line {i}" for i in range(60)))
        ctx = await build_system_context(d)
        assert "## Recent Memory" in ctx
        assert "line 59" in ctx  # last line present
        assert "line 9" not in ctx  # line 10 should be cut (50 limit, 60 lines)
        print("PASS")
    finally:
        (d / "MEMORY.MD").write_text(orig)

asyncio.run(test())
```

### T1.3 — NOTES.MD included in full
1. Write content to NOTES.MD
2. Build context, verify `## Notes` section and full content present

### T1.4 — HEALTH.MD tail included
1. Write 20 error lines to HEALTH.MD
2. Build context, verify only last 10 appear (default `context_health_limit`)

### T1.5 — Empty files omitted
1. Clear MEMORY.MD, NOTES.MD, HEALTH.MD
2. Build context, verify no `## Recent Memory`, `## Notes`, or `## Recent Health Log` sections
3. Only PROMPT.MD content should be present

### T1.6 — Custom limits from CONFIG.md
1. Set `context_memory_limit: 5` in a temp CONFIG.md
2. Write 20 memory lines
3. Build context, verify only last 5 lines included

### T1.7 — Section separators
1. Build context for master (which has non-empty MEMORY.MD)
2. Verify `---` separators between sections

### T1.8 — BaseAgent integration
1. Start REPL, send a message
2. On subsequent turn, agent should reference past actions from memory without explicit `notes_read`
3. (Manual verification — check that master's system prompt includes memory)

---

## Group 2: Planning Agent

### T2.1 — Module imports
```bash
poetry run python -c "from app.agents.planning import planning_agent; print(planning_agent._name)"
# Expected: planning
```

### T2.2 — PROMPT.MD content
```bash
poetry run python -c "
from app.agents.planning.agent import planning_agent
import asyncio
ctx = asyncio.run(planning_agent._read_file('PROMPT.MD'))
assert 'Planning Agent' in ctx
assert 'Delegation Protocol' in ctx
assert 'spawn_agent' in ctx
print('PASS')
"
```

### T2.3 — CONFIG.md tools
```bash
poetry run python -c "
from app.agents.planning.agent import planning_agent
import asyncio
names = asyncio.run(planning_agent._load_tool_names())
assert 'spawn_agent' in names
assert 'check_task_status' in names
assert 'file_read' in names
assert 'file_write' not in names  # Planning doesn't write files
print(f'PASS — {len(names)} tools')
"
```

### T2.4 — CONFIG.md runner values
```bash
poetry run python -c "
from app.agents.base.context import _parse_runner_config
from pathlib import Path
from app.config import settings
cfg = (settings.agents_dir / 'planning' / 'CONFIG.md').read_text()
r = _parse_runner_config(cfg)
assert r['max_turns'] == 30
assert r['task_timeout'] == 600
print('PASS')
"
```

---

## Group 3: Agent Management Tools

### T3.1 — create_agent: valid name
```python
import asyncio
from app.utils.tools.agent_mgmt import CreateAgentTool
import shutil
from app.config import settings

async def test():
    t = CreateAgentTool()
    result = await t.execute(name="test-agent", prompt="You are a test agent.")
    assert "Created agent 'test-agent'" in result
    d = settings.agents_dir / "test-agent"
    assert d.exists()
    assert (d / "PROMPT.MD").read_text() == "You are a test agent."
    assert (d / "CONFIG.md").exists()
    assert (d / "agent.py").exists()
    assert (d / "__init__.py").exists()
    assert (d / "TASK.MD").exists()
    assert (d / "MEMORY.MD").exists()
    # Verify class name in agent.py
    assert "TestAgentAgent" in (d / "agent.py").read_text()
    shutil.rmtree(d)
    print("PASS")

asyncio.run(test())
```

### T3.2 — create_agent: invalid name (uppercase)
```python
result = await CreateAgentTool().execute(name="BadName", prompt="x")
assert "ERROR" in result and "Invalid" in result
```

### T3.3 — create_agent: invalid name (starts with number)
```python
result = await CreateAgentTool().execute(name="123abc", prompt="x")
assert "ERROR" in result
```

### T3.4 — create_agent: protected name refused
```python
result = await CreateAgentTool().execute(name="master", prompt="x")
assert "protected" in result
```

### T3.5 — create_agent: duplicate refused
```python
# Create once, try again
await CreateAgentTool().execute(name="dupe-test", prompt="x")
result = await CreateAgentTool().execute(name="dupe-test", prompt="x")
assert "already exists" in result
# Cleanup
shutil.rmtree(settings.agents_dir / "dupe-test")
```

### T3.6 — create_agent: custom tools
```python
result = await CreateAgentTool().execute(
    name="custom-tools-test", prompt="x", tools=["file_read", "shell_exec"]
)
cfg = (settings.agents_dir / "custom-tools-test" / "CONFIG.md").read_text()
assert "file_read" in cfg
assert "shell_exec" in cfg
assert "file_write" not in cfg  # not in custom list
# Cleanup
shutil.rmtree(settings.agents_dir / "custom-tools-test")
```

### T3.7 — delete_agent: normal delete
```python
await CreateAgentTool().execute(name="del-test", prompt="x")
result = await DeleteAgentTool().execute(name="del-test")
assert "Deleted" in result
assert not (settings.agents_dir / "del-test").exists()
```

### T3.8 — delete_agent: protected name refused
```python
result = await DeleteAgentTool().execute(name="builder")
assert "protected" in result
```

### T3.9 — delete_agent: nonexistent agent
```python
result = await DeleteAgentTool().execute(name="nonexistent-xyz")
assert "not found" in result
```

### T3.10 — delete_agent: running agent refused
```python
# Create agent, write fake STATUS.json with state=running
import json
await CreateAgentTool().execute(name="run-test", prompt="x")
status_path = settings.agents_dir / "run-test" / "STATUS.json"
status_path.write_text(json.dumps({"state": "running", "pid": 99999}))
result = await DeleteAgentTool().execute(name="run-test")
assert "currently running" in result
# Cleanup
shutil.rmtree(settings.agents_dir / "run-test")
```

### T3.11 — Tool registry
```bash
poetry run python -c "
from app.utils.tools import TOOL_REGISTRY
assert 'create_agent' in TOOL_REGISTRY
assert 'delete_agent' in TOOL_REGISTRY
print(f'PASS — {len(TOOL_REGISTRY)} tools in registry')
"
```

### T3.12 — Spinner labels
```bash
poetry run python -c "
from app.cli.renderer import _TOOL_STATUS
assert 'create_agent' in _TOOL_STATUS
assert 'delete_agent' in _TOOL_STATUS
print('PASS')
"
```

---

## Group 4: Builder Agent

### T4.1 — Module imports
```bash
poetry run python -c "from app.agents.builder import builder_agent; print(builder_agent._name)"
# Expected: builder
```

### T4.2 — PROMPT.MD content
```bash
poetry run python -c "
from app.agents.builder.agent import builder_agent
import asyncio
ctx = asyncio.run(builder_agent._read_file('PROMPT.MD'))
assert 'Builder Agent' in ctx
assert 'Read Before Writing' in ctx
assert 'create_agent' in ctx
print('PASS')
"
```

### T4.3 — CONFIG.md tools include file ops + agent mgmt
```bash
poetry run python -c "
from app.agents.builder.agent import builder_agent
import asyncio
names = asyncio.run(builder_agent._load_tool_names())
assert 'file_read' in names
assert 'file_write' in names
assert 'file_edit' in names
assert 'create_agent' in names
assert 'delete_agent' in names
assert 'spawn_agent' not in names  # Builder doesn't delegate
print(f'PASS — {len(names)} tools')
"
```

### T4.4 — CONFIG.md temperature
```python
# Builder should be low temperature (0.2) for precise work
cfg = (settings.agents_dir / "builder" / "CONFIG.md").read_text()
assert "temperature: 0.2" in cfg
```

---

## Group 5: Master Agent Update

### T5.1 — PROMPT.MD no longer mentions stubs
```bash
poetry run python -c "
p = open('app/agents/master/PROMPT.MD').read()
assert 'stub' not in p.lower()
assert 'not yet implemented' not in p.lower()
print('PASS')
"
```

### T5.2 — PROMPT.MD has delegation section
```bash
poetry run python -c "
p = open('app/agents/master/PROMPT.MD').read()
assert '## Delegation' in p or '### When to delegate' in p
assert 'spawn_agent' in p
assert 'check_task_status' in p
assert 'read_task_result' in p
print('PASS')
"
```

### T5.3 — PROMPT.MD tools table updated
```bash
poetry run python -c "
p = open('app/agents/master/PROMPT.MD').read()
assert 'file_write' in p
assert 'file_edit' in p
assert 'file_delete' in p
assert 'spawn_agent' in p
assert 'read_agent_logs' in p
print('PASS')
"
```

### T5.4 — CONFIG.md has new tools
```bash
poetry run python -c "
c = open('app/agents/master/CONFIG.md').read()
assert 'create_agent' in c
assert 'delete_agent' in c
assert 'read_agent_logs' in c
print('PASS')
"
```

### T5.5 — Available agents table
```bash
poetry run python -c "
p = open('app/agents/master/PROMPT.MD').read()
assert 'planning' in p
assert 'builder' in p
assert 'doctor' in p
print('PASS')
"
```

---

## Group 6: CLI Polish

### T6.1 — Cost calculation
```bash
poetry run python -c "
from app.cli.renderer import calc_cost
# Sonnet: $3/M in, $15/M out
c = calc_cost('claude-sonnet-4-6', 1000, 500)
assert abs(c - 0.0105) < 0.0001, f'Got {c}'
# Opus: $15/M in, $75/M out
c2 = calc_cost('claude-opus-4-6', 1000, 500)
assert abs(c2 - 0.0525) < 0.0001, f'Got {c2}'
# Unknown model returns 0
assert calc_cost('unknown', 1000, 500) == 0.0
print('PASS')
"
```

### T6.2 — Cost in status line
1. Start REPL, send a message
2. Verify `$X.XXXX` appears in the status line after the response
3. Send another message, verify session total `($X.XXXX)` appears

### T6.3 — `/cost` command
1. Start REPL, send a couple messages
2. Type `/cost`
3. Verify output shows input tokens, output tokens, total cost

### T6.4 — Tab completion: slash commands
1. Start REPL
2. Type `/` then press Tab
3. Verify command list appears with descriptions

### T6.5 — Tab completion: file mentions
1. Start REPL
2. Type `@app/config/set` then press Tab
3. Verify `@app/config/settings.py` is suggested

### T6.6 — `@` file mention expansion
```bash
poetry run python -c "
from app.cli.main import _expand_file_mentions
result = _expand_file_mentions('Look at @app/config/settings.py please')
assert 'class Settings' in result  # file content should be inlined
assert '\`\`\`' in result  # wrapped in code fences
print('PASS')
"
```

### T6.7 — `@` non-existent file not expanded
```bash
poetry run python -c "
from app.cli.main import _expand_file_mentions
result = _expand_file_mentions('Look at @nonexistent/file.py')
assert '\`\`\`' not in result  # no expansion
assert '@nonexistent/file.py' in result  # left as-is
print('PASS')
"
```

### T6.8 — `!` bash mode
1. Start REPL
2. Type `!ls app/agents`
3. Verify directory listing printed in dim style
4. Verify the command output is NOT sent to the agent (no response follows)

### T6.9 — `!` bash mode timeout
1. Start REPL
2. Type `!sleep 60`
3. Verify "Command timed out (30s)" message appears

### T6.10 — `/diff` command
1. Make a local change (e.g., `echo "# test" >> /tmp/yapoc-test`)
2. Start REPL, type `/diff`
3. If there are git changes, verify syntax-highlighted diff output
4. If no changes, verify "No changes" message

### T6.11 — `/copy` command
1. Start REPL, send a message to get a response
2. Type `/copy`
3. Verify "Copied to clipboard" message
4. Paste from clipboard, verify it matches the last response

### T6.12 — `/copy` with no response
1. Start REPL (fresh)
2. Type `/copy` immediately
3. Verify "No response to copy" message

### T6.13 — `/export` command
1. Start REPL, send a couple messages
2. Type `/export test_export.txt`
3. Verify file created with conversation content
4. Cleanup: `rm test_export.txt`

### T6.14 — `/export` default filename
1. Type `/export` (no argument)
2. Verify `conversation.txt` created
3. Cleanup

### T6.15 — Ctrl+J newline
1. Start REPL
2. Type some text, press Ctrl+J, type more text
3. Verify newline inserted (multiline input)
4. Press Enter to send

### T6.16 — `/help` updated
1. Start REPL, type `/help`
2. Verify output includes: `!command`, `@path`, `/cost`, `/diff`, `/copy`, `/export`, `Ctrl+J`

---

## Integration Tests (Manual, require running server + API key)

### I1 — Context assembly in live REPL
1. `poetry run yapoc`
2. Send: "What is 2+2?"
3. Send: "What did I just ask you?"
4. Agent should reference "2+2" from context memory without calling `notes_read`

### I2 — Delegation chain: create agent
1. `poetry run yapoc`
2. Send: "Create a new agent called 'translator' that translates text to French"
3. Master should delegate to Planning → Planning spawns Builder → Builder calls `create_agent`
4. Verify: `ls app/agents/translator/` shows PROMPT.MD, CONFIG.md, agent.py, __init__.py, TASK.MD, etc.
5. Cleanup: `rm -rf app/agents/translator`

### I3 — Direct execution: simple file task
1. Send: "Write a Python hello world script to projects/hello.py"
2. Master should handle directly (no delegation for simple task)
3. Verify: `cat projects/hello.py` shows hello world script
4. Cleanup: `rm projects/hello.py`

### I4 — Agent status after spawning
1. During I2, run `/agents` or `/status` in another terminal
2. Verify planning/builder show as running with PIDs

### I5 — Cost accumulation across turns
1. Start REPL, send 3-4 messages
2. Check that session cost in status line increases each turn
3. Run `/cost` — total should match status line

---

## Quick Smoke Test Script

Run all non-interactive checks at once:

```bash
poetry run python -c "
import asyncio, shutil, json
from app.config import settings
from app.agents.base.context import build_system_context, _parse_runner_config
from app.agents.planning import planning_agent
from app.agents.builder import builder_agent
from app.agents.master.agent import master_agent
from app.utils.tools import TOOL_REGISTRY
from app.utils.tools.agent_mgmt import CreateAgentTool, DeleteAgentTool
from app.cli.renderer import calc_cost, _TOOL_STATUS
from app.cli.main import _expand_file_mentions

async def run():
    # G1: Context assembly
    ctx = await build_system_context(settings.agents_dir / 'master')
    assert 'Master Agent' in ctx, 'G1: PROMPT missing'

    cfg = (settings.agents_dir / 'planning' / 'CONFIG.md').read_text()
    r = _parse_runner_config(cfg)
    assert r['max_turns'] == 30, 'G1: runner parse failed'

    # G2: Planning agent
    assert planning_agent._name == 'planning', 'G2: name'
    names = await planning_agent._load_tool_names()
    assert 'spawn_agent' in names, 'G2: tools'

    # G3: Agent management tools
    assert 'create_agent' in TOOL_REGISTRY, 'G3: registry'
    assert 'delete_agent' in TOOL_REGISTRY, 'G3: registry'

    t = CreateAgentTool()
    res = await t.execute(name='smoke-test', prompt='Smoke test agent')
    assert 'Created' in res, f'G3: create failed: {res}'
    d = settings.agents_dir / 'smoke-test'
    assert (d / 'PROMPT.MD').exists(), 'G3: PROMPT.MD missing'
    assert (d / 'agent.py').exists(), 'G3: agent.py missing'
    assert 'SmokeTestAgent' in (d / 'agent.py').read_text(), 'G3: class name'

    res = await t.execute(name='master', prompt='x')
    assert 'protected' in res, 'G3: protected check'

    dt = DeleteAgentTool()
    res = await dt.execute(name='smoke-test')
    assert 'Deleted' in res, f'G3: delete failed: {res}'
    assert not d.exists(), 'G3: dir still exists'

    # G4: Builder agent
    assert builder_agent._name == 'builder', 'G4: name'
    bnames = await builder_agent._load_tool_names()
    assert 'create_agent' in bnames, 'G4: tools'

    # G5: Master prompt
    prompt = (settings.agents_dir / 'master' / 'PROMPT.MD').read_text()
    assert 'stub' not in prompt.lower(), 'G5: stubs remain'
    assert 'spawn_agent' in prompt, 'G5: delegation missing'

    config = (settings.agents_dir / 'master' / 'CONFIG.md').read_text()
    assert 'create_agent' in config, 'G5: config tools'

    # G6: Cost + renderer
    assert abs(calc_cost('claude-sonnet-4-6', 1000, 500) - 0.0105) < 0.0001, 'G6: cost calc'
    assert 'create_agent' in _TOOL_STATUS, 'G6: spinner'

    expanded = _expand_file_mentions('Check @app/config/settings.py')
    assert 'class Settings' in expanded, 'G6: file mention expansion'

    print('ALL SMOKE TESTS PASSED')

asyncio.run(run())
"
```
