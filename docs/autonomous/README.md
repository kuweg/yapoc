# YAPOC — Autonomous System Map

*The best from both worlds — Claude Code and OpenClaw.*

This directory is the authoritative design reference for YAPOC's autonomous operation.

---

## What YAPOC is

YAPOC takes the two strongest ideas in personal AI tooling and fuses them:

**From Claude Code:** deep interactive coding — you watch the agent think, approve
tool calls, steer mid-execution, have conversations that build context over time.
The agent reads, writes, and reasons about code with full codebase awareness.

**From OpenClaw:** always-on gateway — fire a task from anywhere (UI, Telegram,
webhook, cron), close the browser, come back to the result. Multi-channel,
persistent, exists independently of whether you are watching.

**From neither (YAPOC's own):** hierarchical multi-agent execution — Master plans,
Planning decomposes, Builder executes, Doctor heals, Cron schedules. Agents spawn
agents. The system self-directs toward goals without human involvement.

OpenClaw explicitly rejected this architecture. Claude Code doesn't have it.
YAPOC does.

---

## Two modes of operation

### Interactive mode (Claude Code feel)

User is present. Chat tab is open. The agent streams thinking, tool calls,
and intermediate results in real-time. User can interrupt, redirect, approve
CONFIRM-tier tools, and have a conversation.

### Autonomous mode (OpenClaw feel)

User fires a task and leaves. The system plans, executes, self-heals, and
delivers the result when ready. CONFIRM-tier tools either auto-approve
(within safety boundaries) or queue for approval.

The system determines the mode based on whether a WebSocket client is actively
observing the task's session. Present = interactive. Absent = autonomous.

---

## Autonomy levels

```
Level 4 — Self-directed     system decides WHAT to do next without being asked
Level 3 — Self-healing      system recovers from failures, governs its own costs
Level 2 — Self-managing     system tracks state, persists, streams, recovers from restarts
Level 1 — Fire-and-forget   system continues executing after the human disconnects
Level 0 — Request-response  system waits for a human to drive every step
```

**YAPOC target: Level 3 solid, Level 4 aspirational.**
Current state: Level 0 at the API boundary, extensive Level 3 infrastructure underneath.

> **M1–M9 complete (April 2026):** 39 tools, 7 agents, SQLite + FTS + embeddings,
> SSE streaming (`POST /task/stream`), notifications, peer delegation, cost tracking
> with budget enforcement (`budget_per_task_usd`, `budget_per_agent_usd`), runaway
> detection, cost dashboard (`GET /metrics/usage`), capability modules, structured
> logging. See `docs/agentic-features-roadmap.md` for details.

Full definitions, requirements, and observable tests: [levels.md](levels.md)

---

## Document index

### Core architecture
| Document | What it covers |
|---|---|
| [levels.md](levels.md) | Autonomy levels — what each level requires, observable tests, current state |
| [architecture.md](architecture.md) | Full system diagram — every component and how they connect |
| [task-lifecycle.md](task-lifecycle.md) | How a task moves from creation to result delivery (interactive + autonomous paths) |

### Capabilities
| Document | What it covers |
|---|---|
| [streaming.md](streaming.md) | Real-time observation — how the UI watches agents think |
| [entry-points.md](entry-points.md) | All the ways a task can enter the system |
| [execution-engine.md](execution-engine.md) | Async dispatcher, agent hierarchy, tool execution |
| [delivery.md](delivery.md) | How results get back to the user (WebSocket, channels) |
| [self-direction.md](self-direction.md) | Goals, cron, resume-on-startup, Doctor as an actor |
| [extensibility.md](extensibility.md) | Plugins, MCP, dynamic tools, skill registry |

### Safety and governance
| Document | What it covers |
|---|---|
| [safety.md](safety.md) | Tool approval policy, autonomy envelopes, guardrails |
| [cost-awareness.md](cost-awareness.md) | Budget enforcement, runaway detection, model routing, cost visibility |
| [risks.md](risks.md) | What's fragile, what's dangerous, what breaks first |

### Planning
| Document | What it covers |
|---|---|
| [roadmap.md](roadmap.md) | What to build, in what order, with acceptance criteria |
