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

## deepseek-v4-flash on the evaluator self-eval ticks (8192 output cap, no tool support)
- status: failed
- decision: Evaluator's scheduled self-eval ticks ran on deepseek/deepseek-v4-flash (max_output=8192, supports_tools=False).
- why: v4-flash's 8192 output-token cap broke REPORT.MD-writing ticks overnight 2026-09-07 (~5 of ~7 ticks failed): finish_reason='length' was treated as a crash by termination.py require_complete(), and a large JSON-escaped file_write of REPORT.MD truncated mid-string → parse_tool_arguments (termination.py:17) hard-failed with no retry → hard crashes plus silent empty `[] OK:` completions. Cluster abated on its own by round 89 (likely provider-side transient), but the no-retry kill-path is a standing defect — don't assign output-cap-constrained, tool-less models to agents that must emit large tool-arg JSON (big file writes) in a single turn.
- by: master (via evaluator round 87/88 diagnostics)
- date: 2026-09-07


## set_task_status crashes on `re.error: bad escape \u` (raw error text through re.sub)
- status: failed
- decision: Pass raw error strings as the replacement argument to re.sub in BaseAgent.set_task_status (base/__init__.py:383).
- why: re.sub treats the replacement as a template, so any `\u` (or other backslash escape) in the error message raises `re.error: bad escape \u`. Recurred 3× (builder CRASH.MD 2×, doctor CRASH.MD 1×, all 2026-05-17). Use str.replace or a lambda/escaped replacement instead of a raw template.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Server startup bind conflict on port 8000
- status: failed
- decision: (Re)start the backend while a previous instance still holds port 8000.
- why: 7 of 8 entries in master/SERVER_CRASH.MD (2026-05-19) are `[Errno 98] address already in use` binding 0.0.0.0:8000 — the auto-restart loop crash-loops on the stale bind. Verify port 8000 is free (or kill the stale PID) before restarting.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Two Telegram bot instances polling the same token
- status: failed
- decision: Run more than one Telegram bot poller against the same bot token.
- why: Recurred 4× in master/SERVER_CRASH.MD as 409 "terminated by other getUpdates request". A leftover second backend instance fights the first for getUpdates and both degrade. Ensure exactly one poller per token.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Letting builder/planning spin to the turn cap on large tasks
- status: failed
- decision: Assign multi-step tasks to builder/planning without decomposing or raising the turn budget.
- why: builder hit "reached the 30-turn limit" 3× and planning "reached the 45-turn limit" 3× on 2026-09-07, silently reporting "incomplete". Decompose large tasks or raise the turn cap rather than letting them spin to the limit.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Librarian tasks under the default timeout
- status: failed
- decision: Run librarian classification/consolidation under the default task timeout.
- why: Librarian timed out 3× (900s once, 600s twice, 2026-09-02→09-07). Raise the timeout for librarian or bound its per-task input size.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Single-shot parse of tool-argument JSON (no retry)
- status: failed
- decision: Parse model-emitted tool-argument JSON once with no retry/repair path.
- why: Evaluator failed 2× on 2026-09-07 with "Incomplete provider response: invalid tool argument JSON" — same defect class as the deepseek-v4-flash truncation entry. Add a retry/repair path and avoid truncation-prone models for large tool-arg JSON.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Master context compaction assumes flat list of strings
- status: failed
- decision: Rely on the context-compaction serializer assuming a flat list of strings.
- why: Master failed 2× on 2026-09-07 with "compaction failed, trimmed context instead: TypeError: sequence item 0: expected str instance, list found" — the serializer receives nested lists. Until fixed, compaction silently degrades to trimming, inflating input:output ratio and cost.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## BaseAgent._name referenced before assignment
- status: failed
- decision: Derive `_memory_dir` from `self._name` before `_name` is assigned in BaseAgent.__init__.
- why: Evaluator crashed 2× (2026-05-24) with `AttributeError: 'BaseAgent' object has no attribute '_name'` at base/__init__.py:327. Initialize `_name` before deriving dependent attributes — an ordering bug, not config.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08

## Builder direct edits to master's protected files trip the security gate
- status: failed
- decision: Have builder perform additive/read-only maintenance on master's protected files via direct file_edit/shell_exec.
- why: Blocked 2× on 2026-09-01 (clearing master's memory index, appending to master's PROMPT.MD) — the integrity gate flags even additive/read-only edits as "Self-destruction". Route such edits through keeper (sanctioned pipeline) instead.
- by: researcher (negative-knowledge sweep)
- date: 2026-09-08
