# Milestone 8: Inter-Agent Collaboration — Manual Test Plan

**Target:** Backend + UI (not CLI)
**Prerequisites:** Server running (`poetry run yapoc start`), frontend running (`pnpm dev` in `app/frontend/`), all API keys configured in `.env`

---

## 8A: Shared Knowledge Base

### Test 1: Basic Knowledge Append

**Setup:** Server running, clean `app/agents/shared/KNOWLEDGE.MD` (header only)

**Steps:**
1. POST to `/task` with body:
   ```json
   {"task": "Use shared_knowledge_append to store the fact that 'YAPOC uses Poetry for dependency management' with category 'convention'"}
   ```
2. Wait for response to complete
3. Check `app/agents/shared/KNOWLEDGE.MD` (via UI file viewer or direct file read)

**Expected:**
- Response confirms success: "Shared knowledge stored by master: ..."
- KNOWLEDGE.MD contains one entry with:
  - `## Entry: convention` header
  - `**Source:** master`
  - `**Time:** YYYY-MM-DD HH:MM` timestamp
  - `**Content:** YAPOC uses Poetry for dependency management`

---

### Test 2: Knowledge Visible in Agent Context

**Setup:** KNOWLEDGE.MD has at least one entry (from Test 1)

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "What shared knowledge entries exist? Check your system context for the Shared Knowledge section and report what you see."}
   ```

**Expected:**
- Master's response references the shared knowledge entry about Poetry
- In agent logs (OUTPUT.MD or debug logs), the system prompt includes a `## Shared Knowledge` section

---

### Test 3: Multiple Agents Append Knowledge

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Delegate a task to planning: have it use shared_knowledge_append to record 'Planning decomposes complex tasks into atomic subtasks' as a 'convention'. Wait for completion, then read KNOWLEDGE.MD and report all entries."}
   ```
2. Wait for the full delegation chain to complete

**Expected:**
- KNOWLEDGE.MD now has 2+ entries
- At least one entry shows `**Source:** planning`
- Entries are ordered chronologically (newest last)

---

### Test 4: Secret Scrubbing in Knowledge

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Use shared_knowledge_append to store: 'The test API key is sk-ant-api03-fake-key-1234567890abcdef'"}
   ```
2. Read `app/agents/shared/KNOWLEDGE.MD`

**Expected:**
- The API key pattern is replaced with `[REDACTED]` in the stored entry
- The tool returns a success message
- The stored content does NOT contain the raw key

---

### Test 5: Entry Cap Enforcement (50 entries)

**Setup:** Manually populate `app/agents/shared/KNOWLEDGE.MD` with 50 `## Entry:` blocks (can use a script or editor)

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Use shared_knowledge_append to store 'This should fail due to cap' as a 'discovery'"}
   ```

**Expected:**
- Tool returns message: "KNOWLEDGE.MD already has 50 entries (max). Oldest entries should be pruned before adding new ones."
- No new entry is appended to the file
- Master reports the cap was hit

---

### Test 6: Knowledge Searchable via search_memory

**Setup:** KNOWLEDGE.MD has entries from earlier tests. Wait for indexer to run (up to 10 min) or restart server to trigger indexing.

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Use search_memory to find shared knowledge about 'Poetry dependency management'. Report what you find."}
   ```

**Expected:**
- `search_memory` returns results with `agent: "shared"` and `source: "KNOWLEDGE.MD"`
- Content matches what was stored in Test 1

---

## 8B: Peer Delegation Protocol

### Test 7: Authorized Peer Delegation (Builder -> Keeper)

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Tell builder to create a test file at app/projects/peer-test.txt with the content 'peer delegation test', and then have builder delegate to keeper to verify that pyproject.toml has the 'anthropic' dependency listed. Report all results."}
   ```
2. Monitor agent activity in the UI dashboard

**Expected:**
- Master spawns builder
- Builder creates the test file
- Builder spawns keeper via `spawn_agent` (peer delegation)
- Keeper's TASK.MD shows `assigned_by: builder`
- Master's HEALTH.MD contains a `[PEER DELEGATION] builder -> keeper: ...` entry
- Both agents complete successfully and report back

---

### Test 8: Unauthorized Peer Delegation (Builder -> Doctor)

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Tell builder to use spawn_agent to delegate a health check task to doctor."}
   ```
2. Monitor response

**Expected:**
- Builder receives an error from `spawn_agent`: "agent 'builder' is not authorized to delegate to 'doctor'"
- Error message lists allowed targets: `['keeper']`
- Doctor's TASK.MD is NOT modified
- Builder reports the delegation failure via `notify_parent`

---

### Test 9: Agent Without delegation_targets Cannot Spawn

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Tell doctor to use spawn_agent to delegate a file creation task to builder."}
   ```
2. Monitor response

**Expected:**
- Doctor (if it has `spawn_agent` in tools) receives error: "agent 'doctor' has no delegation_targets in CONFIG.md"
- If doctor doesn't have `spawn_agent` in its tools, the tool call itself will not be available
- No agent is spawned either way

---

### Test 10: Master Unrestricted Spawning (Backward Compatibility)

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Spawn the planning agent to decompose this task: 'create a hello.txt file in app/projects/ with the text Hello World'. Wait for results."}
   ```
2. Monitor the full delegation chain

**Expected:**
- Master spawns planning without any `delegation_targets` check
- Planning spawns builder without any `delegation_targets` check
- The existing delegation chain works exactly as it did before M8
- No `[PEER DELEGATION]` entries in HEALTH.MD (these are master/planning, which are unrestricted)

---

### Test 11: Peer Delegation Audit Trail

**Setup:** Complete Test 7 first (builder -> keeper delegation)

**Steps:**
1. Read `app/agents/master/HEALTH.MD` (via UI or file read)
2. Search for `[PEER DELEGATION]` entries

**Expected:**
- At least one entry exists: `[YYYY-MM-DD HH:MM] INFO: [PEER DELEGATION] builder -> keeper: <task summary (first 100 chars)>`
- The timestamp is recent (from Test 7)
- The task summary matches what was delegated

---

### Test 12: Concurrent Agent Cap Respected During Peer Delegation

**Setup:** Optionally set `MAX_CONCURRENT_AGENTS=3` in `.env` for easier testing

**Steps:**
1. POST to `/task` with a complex task that triggers multiple spawns:
   ```json
   {"task": "Spawn planning to decompose: 'Create 3 utility files and have keeper verify each one'. This should result in multiple agents running."}
   ```
2. Monitor agent counts in the UI dashboard

**Expected:**
- When the concurrent agent cap is reached, additional `spawn_agent` calls (including peer delegations) return the cap error
- Error message mentions the current live count and the cap value
- No more agents than `max_concurrent_agents` are alive simultaneously

---

## Combined Scenario

### Test 13: End-to-End Collaboration

**Steps:**
1. POST to `/task`:
   ```json
   {"task": "Create a new utility module at app/projects/utils/formatter.py with a format_date function that formats dates as YYYY-MM-DD. After creating it, share the knowledge that 'formatter.py provides date formatting utilities at app/projects/utils/formatter.py' in the shared knowledge base. Then verify pyproject.toml has all required dependencies."}
   ```
2. Monitor the full agent chain in the UI

**Expected:**
- Master delegates to planning (or directly to builder for simple tasks)
- Builder creates `app/projects/utils/formatter.py` with the function
- Builder calls `shared_knowledge_append` to store the knowledge entry
- Builder peer-delegates to keeper for pyproject.toml verification (or master handles this separately)
- KNOWLEDGE.MD has a new entry about formatter.py
- Master's HEALTH.MD shows any peer delegation audit entries
- All agents complete successfully and report results

---

## Cleanup

After testing, you may want to:
1. Remove test files: `app/projects/peer-test.txt`, `app/projects/utils/formatter.py`
2. Reset KNOWLEDGE.MD to just the header: `# Shared Knowledge Base`
3. Clear peer delegation test entries from master's HEALTH.MD
