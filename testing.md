# Testing: Agent Spawn + UI Stale-State Fix

## Setup

```bash
poetry run yapoc start
poetry run yapoc
```

---

## Test 1 — Startup cleanup

After `poetry run yapoc start`, check that any previously-running agents were marked terminated:

```bash
cat app/agents/builder/STATUS.json
cat app/agents/planning/STATUS.json
```

Expected: `"state": "terminated"` (not `"idle"` or `"running"`) if those agents were left over from a prior server run.

---

## Test 2 — Agent spawn works (no silent failure)

In the REPL:

```
> Write "hello world" to a file called test_output.txt in the projects/ directory
```

Expected sequence in AgentSidebar:
1. builder appears with amber dot (`spawning`)
2. builder transitions to amber dot (`running`)
3. After task completes, builder returns to green dot (`idle`)
4. File `projects/test_output.txt` is created with content `hello world`

---

## Test 3 — Spawn works after server restart

1. Stop the server and wait ~15s for PID recycling to potentially occur:

```bash
poetry run yapoc stop
sleep 15
poetry run yapoc start
```

2. Check STATUS.json was cleaned up on restart (state should be `terminated`).

3. Send the same task again:

```
> Write "hello world again" to projects/test_output2.txt
```

Expected: spawn succeeds, file is created. No silent failure.

---

## Test 4 — UI shows correct state (no ghost agents)

1. Restart the server with stale STATUS.json files in place (don't wait for cleanup).
2. Open the AgentSidebar.

Expected: builder/planning show as `idle` with no PID badge — not "live idle" with a stale PID from the previous run.

---

## Cleanup

```
> Delete projects/test_output.txt
> Delete projects/test_output2.txt
```
