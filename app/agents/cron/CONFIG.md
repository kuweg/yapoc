adapter: anthropic
model: claude-haiku-4-5-20251001
temperature: 0.2
tools:
  - spawn_agent
  - ping_agent
  - kill_agent
  - wait_for_agent
  - check_task_status
  - read_task_result
  - file_read
  - file_list
  - memory_append
  - notes_read
  - notes_write
  - health_log
  - notify_parent
  - shared_knowledge_append
delegation_targets:
  - builder
  - keeper
runner:
  max_turns: 20
  task_timeout: 300
  poll_interval: 60
  context_memory_limit: 30
  context_health_limit: 5
