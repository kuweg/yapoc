adapter: lmstudio
model: nvidia/nemotron-3-nano-4b
temperature: 0.2
tools:
  - file_read
  - file_list
  - file_write
  - file_edit
  - shell_exec
  - memory_append
  - notes_read
  - notes_write
  - health_log
  - notify_parent
  - shared_knowledge_append
  # ── Peer delegation ────────────────────────────────────────────────────
  - spawn_agent
  - wait_for_agent
  - check_task_status
delegation_targets:
  - builder
sandbox:
  # Keeper may touch config files and app/config/ only. Everything else
  # (app/agents, app/utils, docs, scripts, etc.) is off-limits — if
  # Keeper ever needs to change code, it should delegate to Builder.
  forbidden:
    - app/agents/
    - app/backend/
    - app/cli/
    - app/utils/
    - docs/
    - scripts/
    - README.md
  # shell_exec is locked down to poetry-only. Keeper is the dependency
  # gatekeeper; it has no legitimate reason to run anything else.
  shell_allowlist:
    - poetry
runner:
  max_turns: 15
  task_timeout: 300
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 10
  context_health_limit: 5
  context_notes_limit: 1500
