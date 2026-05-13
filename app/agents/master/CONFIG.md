adapter: deepseek
model: deepseek-chat
temperature: 0.3
tools:
  # ── Reads (safe, do them yourself) ──────────────────────────────────
  - file_read
  - file_list
  - file_write
  - file_edit
  - file_delete
  - show_agent_settings
  # ── Delegation ──────────────────────────────────────────────────────
  - spawn_agent
  - ping_agent
  - kill_agent
  - wait_for_agent
  - wait_for_agents
  - check_task_status
  - read_task_result
  - verify_task_result
  - read_agent_logs
  # ── Self ────────────────────────────────────────────────────────────
  - server_restart
  - process_restart
  - web_search
  - memory_append
  - notes_read
  - notes_write
  - notes_append
  - health_log
  - agent_amnesia
  - add_task_trace
  - search_memory
  - learnings_append
  - manage_tickets
  - shared_knowledge_append
  - image_read
autonomous_policy:
  file_read:
    auto_approve: ["*"]
  file_write:
    auto_approve: ["*"]
  file_edit:
    auto_approve: ["*"]
  file_delete:
    auto_approve: ["*"]
  file_list:
    auto_approve: ["*"]

sandbox:
  # Master can read anything but writes must go through a sub-agent.
  forbidden:
    - .env
    - app/config/settings.py
    - pyproject.toml
runner:
  max_turns: 12
  task_timeout: 300
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 10
  context_health_limit: 5
  context_notes_limit: 3000
