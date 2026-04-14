adapter: anthropic
model: claude-sonnet-4-6
temperature: 0.2
tools:
  - file_read
  - file_write
  - file_edit
  - file_delete
  - file_list
  - shell_exec
  - web_search
  - create_agent
  - delete_agent
  - notify_parent
  - memory_append
  - notes_read
  - notes_write
  - notes_append
  - health_log
  - add_task_trace
  - search_memory
  - learnings_append
  - shared_knowledge_append
  - image_read
  - parse_csv
  # ── Peer delegation ────────────────────────────────────────────────────
  - spawn_agent
  - wait_for_agent
  - check_task_status
delegation_targets:
  - keeper
sandbox:
  forbidden:
    - app/agents/master/
    - app/agents/planning/
    - app/agents/builder/
    - app/agents/keeper/
    - app/agents/cron/
    - app/agents/doctor/
    - app/agents/model_manager/
    - app/agents/base/
    - app/config/settings.py
    - .env
    - pyproject.toml
autonomous_policy:
  shell_exec:
    auto_approve: ["poetry run pytest*", "poetry run *", "ls *", "cat *", "wc *", "head *", "tail *", "grep *", "find *"]
    deny: ["rm -rf *", "sudo *", "curl * | bash", "wget *", "git push*", "git reset --hard*"]
    default: queue
  file_write:
    auto_approve: ["app/projects/*", "data/*"]
    deny: ["app/config/*", "*.env", "app/agents/*/PROMPT.MD"]
    default: queue
  file_delete:
    deny: ["*"]
    default: deny
  spawn_agent:
    auto_approve: ["*"]
    default: auto_approve
runner:
  max_turns: 15
  task_timeout: 300
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 15
  context_health_limit: 5
  context_notes_limit: 3000
