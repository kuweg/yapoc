adapter: deepseek
model: deepseek-reasoner
temperature: 0.3
tools:
  - file_read
  - file_write
  - file_edit
  - file_delete
  - file_list
  - spawn_agent
  - ping_agent
  - kill_agent
  - wait_for_agent
  - wait_for_agents
  - check_task_status
  - read_task_result
  - verify_task_result
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

delegation_targets:
  - builder
  - keeper
  - model_manager
runner:
  max_turns: 15
  task_timeout: 300
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 20
  context_health_limit: 10
  context_notes_limit: 3000
