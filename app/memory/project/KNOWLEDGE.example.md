# Project Knowledge

Copy this file to `KNOWLEDGE.md` in the same directory. The real `KNOWLEDGE.md`
is git-ignored: it accumulates at runtime as agents learn about your specific
deployment, so it is local state rather than source.

`KNOWLEDGE.md` is injected into every agent's system prompt
(`app/agents/base/context.py`). It and its two siblings — `DECISIONS.md` and
`CONVENTIONS.md`, both optional and created on demand — are indexed
section-by-section under `agent="project"`, so `##` headers are the retrieval
unit.

Durable, project-wide facts belong here. Anything specific to one agent belongs
in that agent's `app/memory/agents/<name>/NOTES.MD` instead.

## Architecture
- Non-obvious structural facts about this deployment.

## Gotchas
- Traps that have already cost someone an hour.

## Operations
- How this instance is actually run, restarted, and monitored.
