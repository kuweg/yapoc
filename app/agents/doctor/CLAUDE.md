# app/agents/doctor — Health Monitor

## What it does
Two modes:
1. **Programmatic** (`run_health_check()`) — pure Python, no LLM, called by APScheduler every 5 min
2. **LLM-driven** (`run_stream_with_tools()`) — handles on-demand tasks spawned by master

## run_health_check()
Scans all agent directories (skips `_*` and `base`):
- Reads HEALTH.MD, CRASH.MD, SERVER_CRASH.MD
- Prunes HEALTH.MD entries older than `settings.health_log_retention_days` (7 days)
- Detects: repeated timeouts (≥3 occurrences) → writes `OPTIMIZATION_SUGGESTION` to that agent's HEALTH.MD
- Detects: high error rates (≥5 errors) → writes `OPTIMIZATION_SUGGESTION`
- Counts crashes via `count_crashes()` (counts `## Crash` headers in CRASH.MD)
- Writes summary to `doctor/HEALTH_SUMMARY.MD` (overwritten each run)
- Appends own MEMORY.MD entry

## CONFIG.md — uses OpenAI, not Anthropic
```yaml
adapter: openai
model: gpt-4o-mini
```
Requires `OPENAI_API_KEY` in `.env`. Without it, all LLM-triggered doctor tasks fail silently (APScheduler catches exceptions). The programmatic `run_health_check()` still works — no LLM needed.

To use Anthropic instead: edit `app/agents/doctor/CONFIG.md`, change adapter to `anthropic` and model to `claude-haiku-4-5-20251001`.

## Singleton
```python
from app.agents.doctor.agent import doctor_agent
```
Imported by `app/backend/main.py`.

## Gotchas
- Optimization suggestions written to other agents' HEALTH.MD appear as `WARNING: OPTIMIZATION_SUGGESTION:` — the doctor's own regex picks these up on the next scan cycle
- Pruning keeps continuation lines (tracebacks without timestamps) attached to their parent entry
- `HEALTH_SUMMARY.MD` is overwritten every run (not appended)
