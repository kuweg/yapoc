adapter: lmstudio
model: nvidia/nemotron-3-nano-4b
temperature: 0.2
tools:
  - file_read
  - file_list
  - read_agent_logs
  - memory_append
  - notes_read
  - notes_write
  - notes_append
  - health_log
  - heal_agent_settings
  - show_agent_settings
  - shared_knowledge_append
runner:
  max_turns: 10
  task_timeout: 120
