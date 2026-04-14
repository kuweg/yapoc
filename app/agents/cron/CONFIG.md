adapter: anthropic
model: claude-3-haiku-20240307
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
  - doctor
  - master
autonomous_policy:
  spawn_agent:
    auto_approve: ["*"]
    default: auto_approve
  kill_agent:
    auto_approve: ["builder", "keeper"]
    deny: ["master", "doctor"]
    default: queue
runner:
  max_turns: 20
  task_timeout: 300
  poll_interval: 60
  context_memory_limit: 30
  context_health_limit: 5
