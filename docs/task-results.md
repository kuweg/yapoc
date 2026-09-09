# Structured task results

Completed queue tasks and agent task-history entries now carry an optional
`structured_result` with `schema_version: 1`. Chat keeps the full assistant answer
and adds a collapsible evidence card. Expand a task in Tasks to see the same card.
The card provides command log links, registered artifact downloads and JSON export.

```json
{
  "schema_version": 1,
  "task_id": "example-run",
  "status": "succeeded",
  "summary": "Drive preview support added",
  "changes": {"files": ["plugins/drive/drive.py"]},
  "verification_status": "checks_passed",
  "verification": [{
    "command": "pytest tests/test_drive_plugin.py",
    "status": "passed",
    "exit_code": 0,
    "evidence_event_seq": 42,
    "evidence_url": "/api/tasks/example-run/evidence/42"
  }],
  "artifacts": [],
  "usage": {
    "input_tokens": 12000,
    "output_tokens": 300,
    "estimated_cost_usd": null,
    "scope": "Direct task stream; excludes delegated agents"
  },
  "limitations": [
    "Command exit codes record execution, not proof that the task objective was met.",
    "File changes cover successful file tools only; shell and delegated edits are not inferred."
  ]
}
```

This example illustrates the schema; it is not a report of a real execution.

## Evidence and status

- The runtime supplies status from execution state: `succeeded`, `partial`,
  `failed`, `blocked`, or `cancelled`. Failed or timed-out execution with saved
  text is `partial`; this means output exists, not that it is correct.
- Summary is assistant output (or an error fallback), limited to 2,000 characters.
  It remains an unverified claim. Model-generated JSON cannot override the record.
- Successful `file_write`, `file_edit`, and `file_delete` tool pairs supply paths.
  These are observed operations, not a final Git diff. Shell/delegated changes
  are not inferred.
- Shell tool return codes supply command checks. All shell commands qualify,
  not just tests. `checks_passed` means all observed command checks exited zero;
  any failed command makes the aggregate `failed`, even if a retry succeeds.
  Missing return codes are `unknown`; no recorded commands is `not_run`.
  Test counts are not extracted from assistant prose.
- Artifacts must exist in the registry with the exact `source_task`. Links or
  pull requests mentioned in prose are not automatically registered artifacts.
- Tokens sum reported usage events for this task ID, excluding delegated agents.
  Repeated model turns count repeated inputs. Unknown values remain `null`;
  actual zero remains zero. Cost is currently `null`: the queue's historical
  cost delta spans concurrent agents and cannot reliably price this scope.
  The live per-model usage bar remains independent.

## Persistence and compatibility

SQLite `task_results` stores the versioned JSON in the same commit as task
completion. Queue results use the queue ID; agent history uses a namespaced
history-row key. Agent continuations sharing a task ID use cumulative journal
evidence for that ID. Evidence collection reads the full journal, not only the
first page. Subsequent terminal-row updates refresh the snapshot.

REST task responses, terminal SSE events (`type: task_result`), completion/error
WebSocket events, reconnect sync and configured webhook callbacks carry the same
saved record. Existing completion receipts prevent duplicate chat delivery.
Chat persistence retains result metadata through reloads.

Older task rows retain their text and return `structured_result: null`; no
historical validation is invented. Interrupted tasks awaiting restart recovery
are not certified complete. The additive schema is created by normal backend
startup; restart the backend to load this code, and rebuild a production UI.

Captured command logs are served as plain text at the evidence URL and scoped
to the task ID and event sequence. Log availability follows journal retention.
Full tool output is not embedded in browser storage or the result JSON.

## Verification

```sh
poetry run pytest tests/test_task_results.py tests/test_db.py tests/test_restart_chat_delivery.py -q
cd app/frontend
pnpm run build --outDir /tmp/yapoc-task-results-build
```

From the repository root, run the isolated Playwright scenario:

```sh
poetry run python scripts/check_restart_chat_browser.py --dist /tmp/yapoc-task-results-build
```

It uses simulated backend events and does not run agents or call providers.
