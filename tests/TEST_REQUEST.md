# YAPOC Full System Test Request

## How to Run

```bash
poetry run yapoc start          # Start the backend server
poetry run yapoc                # Enter the REPL
```

Then paste the test message below into the REPL.

---

## Test Message (paste this into the REPL)

```
I want you to perform a comprehensive system test that exercises all agents and features. Do this as a multi-step task:

1. **Keeper check**: Spawn the keeper agent and ask it to read .env and report which API keys are configured (masked). This tests the keeper agent's config guardian role.

2. **Builder task**: Spawn the builder agent and ask it to create a file at app/projects/test_output.txt containing "YAPOC system test: all agents operational" with a timestamp. This tests file creation via delegation.

3. **Cron setup**: Spawn the cron agent with this task: "add-job: Add a job called 'system-health' that runs the doctor agent every 5 minutes with the task 'Run a full health check on all agents'". This tests the cron agent's schedule management.

4. **Multi-agent coordination**: Spawn the planning agent with this task: "Create a temporary agent called 'test-probe' that reads app/projects/test_output.txt and returns its contents. Then verify the contents match expectations and delete the file." This tests: planning decomposition, temporary agents, builder file I/O, and result aggregation.

5. **Status report**: After all tasks complete, give me a summary of:
   - Which agents were spawned and their final status
   - The keeper's config report
   - The builder's file creation result
   - The cron schedule that was set up
   - The planning agent's coordination result
   - A doctor health check (run it yourself with file_read on app/agents/doctor/HEALTH_SUMMARY.MD)

For steps 1-3, use fire-and-forget (just spawn, don't wait). I'll send my next message after a minute to collect the results. For step 4, use wait_for_agent since it depends on step 2 completing first.
```

---

## What This Tests

| Feature | How It's Tested |
|---------|----------------|
| **Master agent** | Orchestrates the entire multi-step task |
| **Planning agent** | Decomposes step 4 into subtasks, coordinates builder + temp agent |
| **Builder agent** | Creates a test file (step 2) |
| **Keeper agent** | Reads .env and masks secrets (step 1) |
| **Cron agent** | Adds a scheduled job to NOTES.MD (step 3) |
| **Doctor agent** | Health summary is read in step 5 |
| **Fire-and-forget** | Steps 1-3 use spawn without wait_for_agent |
| **Result injection** | After sending next message, completed agent results auto-inject |
| **Toolbar** | While waiting, toolbar shows agent status between turns |
| **Temporary agents** | Step 4 creates and auto-deletes a test-probe agent |
| **wait_for_agent** | Step 4 uses blocking wait |
| **RESUME.MD** | If you Ctrl+C and restart during execution, RESUME.MD captures in-flight tasks |
| **Consumed_at** | Results are collected once and not re-injected |
| **Tool-use loop** | Every agent runs through the full stream_with_tools multi-turn loop |

## Expected Behavior

1. Master spawns keeper, builder, cron agents (fire-and-forget) — returns quickly
2. Toolbar at bottom shows: `Agents: keeper:running | builder:running | cron:running`
3. Master then spawns planning and waits (blocking) for step 4
4. Planning spawns builder to create test-probe, waits for it, then reads the file
5. On your next message, `[System notification: sub-agent tasks completed]` appears with keeper/builder/cron results
6. Master gives final summary

## Quick Verification (non-LLM)

To verify the infrastructure without spending API tokens:

```bash
poetry run python tests/test_full_system.py
```

This runs 66 automated tests covering all components.
