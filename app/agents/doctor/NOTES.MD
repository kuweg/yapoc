
## BertModel LOAD REPORT warning
Observed warning for sentence-transformers/all-MiniLM-L6-v2: `embeddings.position_ids | UNEXPECTED`. Available server logs show the model loads successfully and indexing continues immediately afterward, with no crash or traceback. Current verdict: safe-to-ignore unless future logs show retrieval degradation, load failures, or a broader transformers/sentence-transformers version mismatch.

## Health Check 2026-05-13
- Master: repeated Anthropic authentication/fallback streaming failures in HEALTH.MD.
- Builder: repeated timeout errors; no crash file evidence.
- Planning: repeated timeout errors; warning about stuck TASK.MD after builder completion notification.
- Cost alerts persist for builder, master, and planning.
- Cron, keeper, and model_manager currently show no crash evidence; cron/model_manager HEALTH.MD are empty.
