# Hierarchy Runtime Hardening — Manual Test Plan

Validates the hierarchy upgrades from `docs/hierarchy-development.md`.

## Prerequisites

1. Backend running.
2. Ability to send tasks via `POST /task/stream` (UI or curl).
3. Ability to read files under `app/agents/*/TASK.MD`.

---

## H1: Delegation Boundaries

### Test H1-1: Planning can only delegate to configured targets

**Action**
- Send a task that forces Planning to try spawning a non-allowed agent.
```json
{"task":"Ask planning to spawn doctor with task 'run health check now' and report the tool result."}
```

**Expected**
- `spawn_agent` returns authorization error for planning -> doctor.
- Error mentions `delegation_targets` and allowed targets.
- No `doctor` task is assigned by planning.

### Test H1-2: Planning can still delegate to Builder

**Action**
```json
{"task":"Ask planning to delegate to builder and create app/projects/hierarchy-test.txt with content 'ok'."}
```

**Expected**
- Task succeeds through planning -> builder.
- File is created.

---

## H2: Domain Routing Fail-Fast

### Test H2-1: Config task routed to Builder is rejected

**Action**
```json
{"task":"Use spawn_agent to send builder this task: update pyproject.toml by adding a dependency."}
```

**Expected**
- Spawn rejects with routing mismatch.
- Message includes inferred class (`config`) and suggested target (`keeper` or planning).

### Test H2-2: Code task routed to Keeper is rejected

**Action**
```json
{"task":"Use spawn_agent to send keeper this task: add a new FastAPI endpoint in app/backend/routers/health.py."}
```

**Expected**
- Spawn rejects with routing mismatch.
- Message includes inferred class (`code`) and suggested target (`builder` or planning).

### Test H2-3: Proper routing succeeds

**Action**
```json
{"task":"Delegate to builder to create app/projects/hierarchy-routing-ok.py with a hello() function and verify the file exists."}
```

**Expected**
- Spawn succeeds.
- `app/agents/builder/TASK.MD` frontmatter includes:
  - `task_class: code`
  - `route_target: builder`

---

## H3: Verification Contract

### Test H3-1: Verification metadata exists on delegated task

**Action**
1. Run a builder task through master or planning.
2. Open `app/agents/builder/TASK.MD` after completion.

**Expected**
- Frontmatter includes:
  - `verification_required: true`
  - `verification_status:` (`pending` or `self_reported`)
  - `verified_by:` (may be empty before explicit verification)
  - `verified_at:` (may be empty before explicit verification)

### Test H3-2: Explicit verification updates frontmatter

**Action**
```json
{"task":"Call verify_task_result for builder with verdict verified and notes 'manual check passed', then read builder task status."}
```

**Expected**
- Tool confirms verification.
- `builder/TASK.MD` shows:
  - `verification_status: verified`
  - `verified_by: master` (or caller agent name)
  - `verified_at:` populated
- `## Verification` section exists in the task file.

### Test H3-3: Wait/read tools surface verification state

**Action**
- Use `check_task_status`, `wait_for_agent`, or `read_task_result` for builder.

**Expected**
- Returned text includes `[verification] required=..., status=...`.

---

## H4: Master Routing Context

### Test H4-1: Routing classifier appears in master prompt flow

**Action**
1. Submit one code-heavy task and one config-heavy task.
2. Inspect `app/agents/master/OUTPUT.MD` (or turn logs).

**Expected**
- Master context contains a `[SYSTEM ROUTING CLASSIFIER]` block with:
  - `task_class`
  - `suggested_agent`
  - `confidence`
  - `verification_required`

---

## H5: Metrics / Evidence

### Test H5-1: Hierarchy metrics endpoint returns data

**Action**
```bash
curl -s http://localhost:8000/metrics/hierarchy
```

**Expected**
- JSON response with:
  - `total_task_records`
  - `delegated_by_parent`
  - `task_class_counts`
  - `success_rate_by_task_class`
  - `verification_required_count`
  - `verification_verified_count`
  - `verification_pending_count`
  - `average_completion_seconds_by_parent`

### Test H5-2: Metrics move after new tasks

**Action**
1. Record `/metrics/hierarchy`.
2. Run 2-3 delegated tasks (at least one code task).
3. Query `/metrics/hierarchy` again.

**Expected**
- `total_task_records` increases.
- `task_class_counts.code` (or another relevant class) increases.
- Verification counters update accordingly.

---

## Cleanup

1. Remove temporary files created for this test:
   - `app/projects/hierarchy-test.txt`
   - `app/projects/hierarchy-routing-ok.py`
2. Optionally clear temporary agent task files if needed for a clean dashboard state.
