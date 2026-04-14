adapter: anthropic
model: claude-haiku-4-5-20251001
temperature: 0.2
tools:
  - file_read
  - file_list
  - file_write
  - file_edit
  - check_model_availability
  - list_models
  - memory_append
  - notes_read
  - notes_write
  - health_log
  - shared_knowledge_append
runner:
  max_turns: 15
  task_timeout: 120
