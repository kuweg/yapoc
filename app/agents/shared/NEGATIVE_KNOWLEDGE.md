# Negative Knowledge Store
<!--
  Persistent, searchable record of "things we tried that didn't work" —
  rejected approaches, dead-end designs, and failed experiments.
  Future work must NOT re-litigate these. When librarian classifies a
  thought as a rejected approach / failed experiment, it APPENDS an entry
  here (see app/agents/librarian/PROMPT.MD "How to route" section).

  Entry format:

  ## <short-title>
  - status: rejected | failed | obsolete | superseded
  - decision: <one-line description of the approach/design>
  - why: <why it was rejected/failed — the technical reason, 1-3 sentences>
  - by: <agent that recorded it, e.g. master/builder/evaluator>
  - date: YYYY-MM-DD
-->

## context_compact_model misconfigured to dead model id
- status: failed
- decision: context_compact_model was set to claude-haiku-4-5-20251001
- why: That is a dead/nonexistent Anthropic model id — the provider silently failed, which disabled context compaction entirely and drove master's input:output ratio to 112:1 (82% of spend). Fixed by switching to deepseek-chat for compaction.
- by: master
- date: 2026-08-30

## AUTO-FIX items applied as non-transactional config edits
- status: superseded
- decision: Evaluator's AUTO-FIX suggestions were applied directly as inline non-transactional config edits.
- why: Edits outside the sanctioned pipeline could clobber each other or be applied out of order. Now the evaluator→master auto-fix loop applies them pre-authorized via keeper, so all config mutations go through the sanctioned pipeline.
- by: evaluator
- date: 2026-08-30

## Master spawning sub-agents just to cat a file / read a config
- status: rejected
- decision: Master (or planning) spawned a sub-agent purely to perform a read-only lookup (cat a file, read a config).
- why: A full spawn is a ~30s round trip for a 0.1s read. Master and planning now use the tool ladder (file_read / file_list / show_agent_settings) for read-only lookups instead of spawning.
- by: master
- date: 2026-08-30

## route_all_work_exclusively_through_planning
- status: rejected
- decision: Route ALL work exclusively through the planning agent.
- why: It added a planning hop to trivial tasks for no benefit. Direct-to-builder/keeper routing is correct for complexity ≤ 6; planning is reserved for complexity ≥ 7.
- by: planning
- date: 2026-08-31

## grep tool in builder's shell unreliable
- status: failed
- decision: Rely on the in-sandbox grep tool to verify code/marker presence.
- why: grep inside the build sandbox returned no matches for patterns that shell_exec.confirmed actually exist on disk (false negatives). Prefer reading the actual file lines to verify edits rather than trusting the grep result.
- by: builder
- date: 2026-08-31
