adapter: anthropic
model: claude-3-haiku-20240307
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
  # ── Delegation (Phase 7 — Doctor as actor) ────────────────────
  - spawn_agent
  - kill_agent
  - check_task_status
delegation_targets:
  - builder
  - planning
autonomy_envelope:
  can_kill_agents: [builder, keeper, cron]
  cannot_kill: [master, doctor]
  can_create_tasks: true
  max_tasks_per_run: 3
autonomous_policy:
  shell_exec:
    auto_approve: ["ps aux*", "top -bn1*", "df -h*", "free -m*"]
    deny: ["rm *", "sudo *", "kill *"]
    default: deny
  file_read:
    auto_approve: ["*"]
    default: auto_approve
  file_list:
    auto_approve: ["*"]
    default: auto_approve
runner:
  max_turns: 10
  task_timeout: 120
