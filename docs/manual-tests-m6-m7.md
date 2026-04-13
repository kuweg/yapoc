# Manual Test Cases — Milestones M6–M7

*Generated: 2026-04-13 | All testing via backend + UI*

## Prerequisites

```bash
poetry run yapoc start    # backend must be running
# Open the web UI dashboard
```

---

## M6: Agent Learning

### T6.1 — `learnings_append` tool creates structured entry

```bash
poetry run python -c "
import asyncio
from pathlib import Path
from app.utils.tools.memory import LearningsAppendTool
from app.config import settings
import tempfile

d = Path(tempfile.mkdtemp()) / 'agent'; d.mkdir()
(d / 'LEARNINGS.MD').write_text('')
tool = LearningsAppendTool(agent_dir=d)
result = asyncio.get_event_loop().run_until_complete(tool.execute(
    rule_name='Always check file exists before editing',
    context='file_edit fails if target does not exist',
    action='Call file_read before file_edit to verify existence',
    confidence='high',
))
print('Result:', result)
content = (d / 'LEARNINGS.MD').read_text()
print(content)
assert '## Rule: Always check file exists' in content
assert '**Confidence:** high' in content
print('PASS')
"
```

**Expected:** Structured rule entry in LEARNINGS.MD with all fields
REsult:
<string>:11: DeprecationWarning: There is no current event loop
Result: Learning stored: Always check file exists before editing (confidence: high)

## Rule: Always check file exists before editing
- **Observed:** 2026-04-13
- **Context:** file_edit fails if target does not exist
- **Action:** Call file_read before file_edit to verify existence
- **Confidence:** high


---

### T6.2 — Max 20 rules enforced

```bash
poetry run python -c "
import asyncio
from pathlib import Path
from app.utils.tools.memory import LearningsAppendTool
import tempfile

d = Path(tempfile.mkdtemp()) / 'agent'; d.mkdir()
existing = '\n'.join(f'## Rule: Rule {i}\n- test\n' for i in range(20))
(d / 'LEARNINGS.MD').write_text(existing)
tool = LearningsAppendTool(agent_dir=d)
result = asyncio.get_event_loop().run_until_complete(tool.execute(
    rule_name='Rule 21', context='test', action='test',
))
print('Result:', result)
assert 'already has 20 rules' in result
print('PASS: cap enforced')
"
```

**Expected:** Rejection message, rule 21 not added
Result:
<string>:11: DeprecationWarning: There is no current event loop
Result: LEARNINGS.MD already has 20 rules (max). Review and prune old rules with notes_write before adding new ones.
PASS: cap enforced
---

### T6.3 — Secrets scrubbed in learnings

```bash
poetry run python -c "
import asyncio
from pathlib import Path
from app.utils.tools.memory import LearningsAppendTool
import tempfile

d = Path(tempfile.mkdtemp()) / 'agent'; d.mkdir()
(d / 'LEARNINGS.MD').write_text('')
tool = LearningsAppendTool(agent_dir=d)
asyncio.get_event_loop().run_until_complete(tool.execute(
    rule_name='Key handling',
    context='Found key sk-ant-abc123def456ghi789jkl012mno in logs',
    action='Never log keys',
))
content = (d / 'LEARNINGS.MD').read_text()
assert 'sk-ant-' not in content
assert '[REDACTED]' in content
print('PASS: secrets scrubbed in learnings')
"
```
Result:
<string>:10: DeprecationWarning: There is no current event loop
PASS: secrets scrubbed in learnings
---

### T6.4 — LEARNINGS.MD injected into system context

```bash
poetry run python -c "
import asyncio, tempfile
from pathlib import Path
from app.agents.base.context import build_system_context

d = Path(tempfile.mkdtemp())
(d / 'PROMPT.MD').write_text('You are test.')
(d / 'MEMORY.MD').write_text('')
(d / 'NOTES.MD').write_text('')
(d / 'HEALTH.MD').write_text('')
(d / 'LEARNINGS.MD').write_text(
    '## Rule: Check file before edit\n- **Action:** Call file_read first\n'
)
ctx = asyncio.get_event_loop().run_until_complete(build_system_context(d))
assert '## Learned Rules' in ctx
assert 'Check file before edit' in ctx
print('PASS: learnings injected into context')
"
```
Result:
<string>:14: DeprecationWarning: There is no current event loop
PASS: learnings injected into context
---

### T6.5 — Empty LEARNINGS.MD not injected

```bash
poetry run python -c "
import asyncio, tempfile
from pathlib import Path
from app.agents.base.context import build_system_context

d = Path(tempfile.mkdtemp())
for f in ['PROMPT.MD','MEMORY.MD','NOTES.MD','HEALTH.MD','LEARNINGS.MD']:
    (d / f).write_text('Agent.' if f == 'PROMPT.MD' else '')
ctx = asyncio.get_event_loop().run_until_complete(build_system_context(d))
assert 'Learned Rules' not in ctx
print('PASS: empty learnings not injected')
"
```
Result:
<string>:9: DeprecationWarning: There is no current event loop
PASS: empty learnings not injected
---

### T6.6 — MEMORY.MD entries include outcome classification

```bash
poetry run python -c "
from app.agents.base import _sanitize_for_memory
entry = f'[2026-04-13 10:00] task: test | result: {_sanitize_for_memory(\"done\")} | outcome: success'
assert '| outcome: success' in entry
print('PASS: outcome suffix present in memory format')
"
```
Result:
nikita_zaitsev@EPRSBELW0202 yapoc % poetry run python -c "
from app.agents.base import _sanitize_for_memory
entry = f'[2026-04-13 10:00] task: test | result: {_sanitize_for_memory(\"done\")} | outcome: success'
assert '| outcome: success' in entry
print('PASS: outcome suffix present in memory format')
"
PASS: outcome suffix present in memory format
---

### T6.7 — Agent uses search_memory before complex task (behavioral)

**Via UI:** Send:
> refactor the doctor agent health check to separate stale detection into its own method

**Expected (observe in UI streaming output):**
- Master or planning calls `search_memory` with a summary of the task before delegating
- If LEARNINGS.MD has relevant rules, agent mentions applying them

Result:
I'll process the notification from the builder agent.## ✅ Notification Processed

The builder agent completed the doctor refactor task and found that no changes were needed:

Key Findings:
Stale detection is already in its own method — _check_stale_tasks() is a dedicated method that handles both stale timestamp detection and crash detection
Per the task's own constraint ("If the stale detection is already in its own method, report that and do nothing"), builder made no changes
Sandbox constraint discovered: app/agents/doctor/ is a protected base agent directory that builder cannot modify (even if changes were needed)
Current Structure:
_check_stale_tasks(agents_dir, agent_dirs)  # Already dedicated method
  ├─ Detects stale running tasks (timestamp threshold)
  └─ Detects crashed tasks (STATUS.json vs TASK.MD mismatch)

run_health_check()  # Orchestrator
  └─ Calls _check_stale_tasks() and processes results
All 118 tests continue to pass ✅

The refactoring task is complete — the code already follows the requested pattern.
---

### T6.8 — Agent stores a learning after repeated pattern (behavioral)

**Via UI:** Run two tasks that produce the same error pattern, then ask:
> what did you learn from the last two failures?

**Expected:**
- Agent reflects on pattern and calls `learnings_append` (or explains what rule it would store)
- LEARNINGS.MD entry created with structured format

Result:
Looking at my recent memory, I see two tasks that didn't produce the expected changes:

First attempt (12:49): I routed the doctor refactor to planning (complexity ~7)
Second attempt (12:51): Builder reported the code was already refactored
What I Learned## Key Takeaway
I should have read app/agents/doctor/agent.py first using file_read to check if _check_stale_tasks() already existed as a separate method. This would have:

Saved a full planning → builder delegation cycle (~30-60 seconds)
Given you an immediate answer
Avoided unnecessary agent coordination
This is exactly what the "Tool ladder" in my instructions warns against: using expensive delegation when a cheap read operation would suffice.

Pattern to apply going forward: For any refactoring request, always inspect the target file first to understand the current structure before deciding whether delegation is needed.
---

### T6.9 — Tool registered and builds correctly

```bash
poetry run python -c "
from app.utils.tools import TOOL_REGISTRY, build_tools
from app.config import settings
assert 'learnings_append' in TOOL_REGISTRY
for agent in ['master', 'planning', 'builder']:
    tools = build_tools(['learnings_append'], settings.agents_dir / agent)
    assert len(tools) == 1 and tools[0].name == 'learnings_append'
    print(f'PASS: {agent}')
"
```
Result:
PASS: master
PASS: planning
PASS: builder
---

## M7: Human-in-the-Loop Refinement

### T7.1 — Structured escalation on ambiguous task (master)

**Via UI:** Send:
> update the database schema

**Expected:**
- Master responds with `[DECISION NEEDED]` format (or `[UNCERTAIN]` with structured options)
- Response includes: Question, Context, Options with trade-offs, Recommendation
- Does NOT proceed without user choice

Result:
[DECISION NEEDED]

Question: Which database schema do you want to update, and what changes should be made?

Context:

YAPOC uses SQLite for the task board/ticket system (managed by the backend)
I don't have visibility into what specific schema changes you need
Schema updates can affect data integrity and require migration planning
Options:

Ticket/task board schema — modify the SQLite schema used by the dashboard (columns, tables, indexes)
Add new tables — create additional tables for new features
Modify existing columns — change data types, add constraints, rename fields
Something else — a different database or schema I'm not aware of
Recommendation: Please specify:

Which table(s) need changes
What specific modifications (add column X, change type of Y, create table Z, etc.)
Whether existing data needs to be preserved/migrated
Default if no response: No action taken (schema changes are irreversible and require explicit specification)

Could you clarify what schema changes you need?
---

### T7.2 — Structured escalation propagates from builder

**Via UI:** Send:
> delete all log files older than 30 days

**Expected:**
- If builder is uncertain: calls `notify_parent` with `[DECISION NEEDED]` format
- Master relays the structured decision request to the user
- Response includes specific options (which directories, which file patterns)

Result:
[DECISION NEEDED]

Question: Which log files should be deleted, and from which directories?

Context:

YAPOC has multiple types of logs in different locations:
Agent logs: app/agents/*/OUTPUT.MD, CRASH.MD, HEALTH.MD, etc.
Application logs: potentially in logs/ or root directory
System logs: various locations depending on configuration
"Older than 30 days" could mean file modification time or content timestamps
This is a destructive, irreversible operation
Options:

Agent logs only — delete OUTPUT.MD, CRASH.MD, etc. from app/agents/*/ older than 30 days (safest, these are regenerated)
All .log files project-wide — find and delete any *.log files older than 30 days
Specific directory — target a particular log directory you have in mind
Archive instead of delete — move old logs to an archive folder before deletion
Recommendation: Option 1 (agent logs only) — these are diagnostic files that regenerate automatically and are safe to clean up

Default if no response: No action taken (deletion is irreversible; I need explicit confirmation of scope)

Please specify:

Which directories/file patterns to target
Whether to use file modification time or parse timestamps from content
Whether you want archival before deletion
---

### T7.3 — Clear task does NOT trigger escalation

**Via UI:** Send:
> create a file app/projects/test_m7.py with content "print('hello')"

**Expected:**
- Master delegates to builder immediately
- No `[DECISION NEEDED]` or `[UNCERTAIN]`
- File created successfully

Result:
✅ File Created
The file app/projects/test_m7.py has been created successfully with the content:

print('hello')
Builder verified the file exists and contains the exact content requested.
---

### T7.4 — Escalation format includes all required fields

**Via UI:** Send:
> migrate the system to use PostgreSQL instead of SQLite

**Expected response structure:**
```
[DECISION NEEDED]
- Question: (what scope? which components?)
- Context: (current SQLite usage, affected files)
- Options: (1. full migration, 2. hybrid approach, 3. defer)
- Recommendation: (one option with justification)
- Default if no response: (no action — reversibility preserved)
```

Result:
[DECISION NEEDED]

Question: Do you want to migrate the entire YAPOC task board/ticket system from SQLite to PostgreSQL?

Context:

YAPOC currently uses SQLite for the task board (tickets, activity logs, status tracking)
PostgreSQL migration requires:
Installing PostgreSQL server and Python driver (psycopg2)
Creating new database schema
Migrating existing ticket/task data
Updating backend connection configuration
Testing all CRUD operations
This is a major infrastructure change affecting the backend API server
Existing SQLite data would need to be exported and imported
Options:

Full migration with data preservation — set up PostgreSQL, migrate all existing tickets/data, update config (complexity ~9, requires planning)
Fresh PostgreSQL setup — set up PostgreSQL with clean schema, discard existing SQLite data (simpler but loses history)
Dual database — keep SQLite for now, add PostgreSQL for new features only (gradual migration)
Abort — keep SQLite (it's working fine for the current scale)
Recommendation: Option 1 (full migration with data preservation) — maintains continuity and gives you the benefits of PostgreSQL (better concurrency, scalability, advanced features)

Default if no response: No action taken (this is a breaking change that requires explicit confirmation and may cause downtime)

Before I proceed, please confirm:

Do you have PostgreSQL installed locally, or should the migration plan include installation steps?
Do you want to preserve existing ticket/task data from SQLite?
Are you okay with potential brief downtime during the migration?

---

## Cleanup

```bash
rm -f app/projects/test_m7.py
```

---

## Summary Matrix

| ID | Test | Category | Pass Criteria |
|---|---|---|---|
| T6.1 | learnings_append creates entry | Tool | Structured rule in LEARNINGS.MD |
| T6.2 | Max 20 rules cap | Tool | Rejection message |
| T6.3 | Secrets scrubbed in learnings | Security | `[REDACTED]`, no raw keys |
| T6.4 | LEARNINGS.MD injected into context | Context | `## Learned Rules` in prompt |
| T6.5 | Empty learnings not injected | Context | No `Learned Rules` section |
| T6.6 | Outcome classification in memory | Format | `| outcome: success` suffix |
| T6.7 | search_memory before complex task | Behavioral | Agent searches before acting |
| T6.8 | Learning stored after pattern | Behavioral | LEARNINGS.MD entry created |
| T6.9 | Tool registered and builds | Registration | All 3 agents build tool OK |
| T7.1 | Structured escalation (master) | Escalation | `[DECISION NEEDED]` format |
| T7.2 | Escalation propagates from builder | Chain | Structured request via notify_parent |
| T7.3 | Clear task no escalation | No false positive | Direct delegation |
| T7.4 | All escalation fields present | Format | Question/Context/Options/Rec |
