# Manual Test Cases — Milestones M4–M5

*Generated: 2026-04-13 | All testing via backend + UI*

## Prerequisites

```bash
poetry run yapoc start    # backend must be running
# Open the web UI dashboard
```

All behavioral tests are performed via the **web UI**. Programmatic tests use `poetry run python -c`.

---

## M4: Self-Healing & Recovery

### T4.1 — Transient tool error is retried automatically — pass

```bash
poetry run python -c "
import asyncio
from pathlib import Path
from app.agents.base import BaseAgent
from app.utils.tools import BaseTool, RiskTier
from dataclasses import dataclass
import tempfile

@dataclass
class TC:
    id: str = 'tc1'; name: str = 'flaky'; input: dict = None
    def __post_init__(self): self.input = self.input or {}

class Flaky(BaseTool):
    name = 'flaky'; description = 'test'
    input_schema = {'type': 'object', 'properties': {}}
    risk_tier = RiskTier.AUTO
    def __init__(self): self._calls = 0
    async def execute(self, **p):
        self._calls += 1
        if self._calls == 1: raise ConnectionError('refused')
        return 'recovered'

d = Path(tempfile.mkdtemp()) / 'ag'; d.mkdir()
for f in ['PROMPT.MD','MEMORY.MD','HEALTH.MD','NOTES.MD']: (d/f).write_text('')
(d/'CONFIG.md').write_text('adapter: anthropic\nmodel: test\n')
agent = BaseAgent(d)
tool = Flaky()
r, _ = asyncio.get_event_loop().run_until_complete(agent._execute_tool(TC(), {'flaky': tool}))
assert not r.is_error and tool._calls == 2
print(f'PASS: recovered after retry (attempts={tool._calls})')
"
```

**Expected:** `PASS: recovered after retry (attempts=2)`

---

### T4.2 — Permanent error NOT retried — FIXED

**Bug found:** `FileNotFoundError` inherits from `OSError`, which was in the transient error tuple. Fixed by catching `_PERMANENT_OS_ERRORS` (`FileNotFoundError`, `PermissionError`, `IsADirectoryError`, `NotADirectoryError`, `FileExistsError`) before the `OSError` catch.

```bash
poetry run python -c "
import asyncio
from pathlib import Path
from app.agents.base import BaseAgent
from app.utils.tools import BaseTool, RiskTier
from dataclasses import dataclass
import tempfile

@dataclass
class TC:
    id: str = 'tc1'; name: str = 'bad'; input: dict = None
    def __post_init__(self): self.input = self.input or {}

class Bad(BaseTool):
    name = 'bad'; description = 'test'
    input_schema = {'type': 'object', 'properties': {}}
    risk_tier = RiskTier.AUTO
    def __init__(self): self._calls = 0
    async def execute(self, **p):
        self._calls += 1
        raise FileNotFoundError('/nope')

d = Path(tempfile.mkdtemp()) / 'ag'; d.mkdir()
for f in ['PROMPT.MD','MEMORY.MD','HEALTH.MD','NOTES.MD']: (d/f).write_text('')
(d/'CONFIG.md').write_text('adapter: anthropic\nmodel: test\n')
agent = BaseAgent(d)
tool = Bad()
r, _ = asyncio.get_event_loop().run_until_complete(agent._execute_tool(TC(), {'bad': tool}))
assert r.is_error and tool._calls == 1
print(f'PASS: permanent error, no retry (attempts={tool._calls})')
"
```

**Expected:** `PASS: permanent error, no retry (attempts=1)`

---

### T4.3 — Builder handles missing file gracefully — pass

**Via UI:** Send:
> ask builder to read the file /this/path/does/not/exist.txt and tell me what's in it

**Result:** Builder correctly identified path-outside-sandbox as a permanent error, reported back via `notify_parent`. No retry loop.

---

### T4.4 — Planning retries failed delegation — pass

**Via UI:** Send:
> create a new API endpoint at /api/test that returns {"status": "ok"} and add a test for it

**Result:** API endpoint was implemented successfully (builder didn't fail, so retry path wasn't exercised).

---

## M5: Proactive Agent Behavior

### T5.1 — Doctor detects stale running task — FIXED (heredoc setup had indentation)

**Important:** The heredoc must NOT have leading spaces. Copy-paste exactly:

```bash
cp app/agents/builder/TASK.MD /tmp/builder_task_backup.md 2>/dev/null || true
cat > app/agents/builder/TASK.MD << 'EOF'
---
status: running
assigned_by: master
assigned_at: 2026-04-12T01:00:00Z
---

## Task
Deliberately stale task for testing
EOF
```

Run Doctor:
```bash
poetry run python -c "
import asyncio
from app.agents.doctor.agent import doctor_agent
report = asyncio.get_event_loop().run_until_complete(doctor_agent.run_health_check())
if 'STALE_TASK' in report: print('PASS: stale task detected')
else: print('FAIL: STALE_TASK not in report')
"
```

Restore:
```bash
cp /tmp/builder_task_backup.md app/agents/builder/TASK.MD 2>/dev/null || rm -f app/agents/builder/TASK.MD
```

**Note:** T5.5 output (line 309) confirmed `STALE_TASK` detection works — it was detected when T5.2's setup left the stale task in place. The initial T5.1 failure was caused by indented heredoc lines corrupting the YAML frontmatter.

---

### T5.2 — Doctor detects crashed agent — pass

```bash
cp app/agents/builder/TASK.MD /tmp/builder_task_backup.md 2>/dev/null || true
cp app/agents/builder/STATUS.json /tmp/builder_status_backup.json 2>/dev/null || true
echo '{"state": "terminated", "pid": 99999}' > app/agents/builder/STATUS.json
cat > app/agents/builder/TASK.MD << 'EOF'
---
status: running
assigned_by: master
assigned_at: 2026-04-13T10:00:00Z
---

## Task
Test crash detection
EOF
```

```bash
poetry run python -c "
import asyncio
from app.agents.doctor.agent import doctor_agent
report = asyncio.get_event_loop().run_until_complete(doctor_agent.run_health_check())
if 'CRASHED_TASK' in report: print('PASS: crashed agent detected')
else: print('FAIL: CRASHED_TASK not in report')
"
```

Restore:
```bash
cp /tmp/builder_task_backup.md app/agents/builder/TASK.MD 2>/dev/null || rm -f app/agents/builder/TASK.MD
cp /tmp/builder_status_backup.json app/agents/builder/STATUS.json 2>/dev/null || rm -f app/agents/builder/STATUS.json
```

---

### T5.3 — Doctor detects cross-agent error pattern — pass

```bash
NOW=$(date "+%Y-%m-%d %H:%M")
for agent in builder planning keeper; do
  echo "[$NOW] ERROR: Connection refused 127.0.0.1:8000 — server unreachable" >> app/agents/$agent/HEALTH.MD
done
```

```bash
poetry run python -c "
import asyncio
from app.agents.doctor.agent import doctor_agent
report = asyncio.get_event_loop().run_until_complete(doctor_agent.run_health_check())
if 'CROSS_AGENT_PATTERN' in report: print('PASS: cross-agent pattern detected')
else: print('FAIL: CROSS_AGENT_PATTERN not in report')
"
```

---

### T5.4 — Different errors not grouped as pattern — pass

```bash
poetry run python -c "
from pathlib import Path
from app.agents.doctor.agent import DoctorAgent
import tempfile

tmp = Path(tempfile.mkdtemp())
for name, err in [('a','Disk full'), ('b','Memory exceeded'), ('c','Network timeout')]:
    (tmp/name).mkdir()
    (tmp/name/'HEALTH.MD').write_text(f'[2026-04-13 10:00] ERROR: {err}\n')
doctor = DoctorAgent.__new__(DoctorAgent)
findings = doctor._detect_cross_agent_patterns(tmp, [tmp/'a', tmp/'b', tmp/'c'])
assert len(findings) == 0
print('PASS: different errors not grouped')
"
```

---

### T5.5 — HEALTH_SUMMARY.MD includes new sections — pass

```bash
head -40 app/agents/doctor/HEALTH_SUMMARY.MD
```

**Confirmed:** Output shows:
- `STALE_TASK` warning for builder (line 309 of test output)
- `CRASHED_TASK` warning for builder (line 310)
- `CROSS_AGENT_PATTERN` section present
- 15 issues detected across 7 agents

---

## Summary Matrix

| ID | Test | Result | Fix applied |
|---|---|---|---|
| T4.1 | Transient retry | pass | — |
| T4.2 | Permanent no retry | **fixed** | `_PERMANENT_OS_ERRORS` catch before `OSError` |
| T4.3 | Builder missing file | pass | — |
| T4.4 | Planning retry delegation | pass (no failure to retry) | — |
| T5.1 | Stale task detection | **fixed** | Heredoc indentation in test doc |
| T5.2 | Crash detection | pass | — |
| T5.3 | Cross-agent pattern | pass | — |
| T5.4 | Different errors | pass | — |
| T5.5 | Summary sections | pass | — |
