
## Telegram Bot
2026-05-24: All bot messages now reply to the triggering user message. _handle_command, _handle_auth, and the auth-required branch all pass reply_to_message_id from the incoming message_id.

## Performance
2026-05-25: User reported builder agent is too slow. Needs timeout/performance review. Consider reviewing task_timeout, model assignment, or parallelization strategy.
