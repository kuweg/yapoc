# YAPOC Autonomous Design Document

> **YAPOC** — Yet Another OpenClaw
> Inspired by OpenClaw, built from scratch as a self-hosted multi-agent orchestration system.

---

## 1. What is OpenClaw?

OpenClaw is an **open-source, self-hosted AI agent gateway** that connects chat platforms (WhatsApp, Telegram, Discord, Slack, 30+) to autonomous AI agents. Created by Peter Steinberger (originally as "Clawdbot" in Nov 2025), it has grown to **347,000+ GitHub stars** as of April 2026.

### Core Philosophy

- **Agents configured via Markdown** — not code. PROMPT.MD files define agent behavior.
- **Gateway daemon** — persistent server that routes messages, manages sessions, and orchestrates agents.
- **Channel-first** — agents are accessed through chat interfaces (WhatsApp, Telegram, etc.).
- **Self-hosted** — runs on your own infrastructure, no cloud dependency.

### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-agent routing** | Run multiple isolated agents in one Gateway, each with its own identity, workspace, memory |
| **Sub-agents** | Spawn background agents for parallel work — research, code, analysis |
| **Agent Teams** | LangGraph-style orchestration with task queues and handoffs |
| **Cron scheduling** | Time-based agent wake-ups and recurring tasks |
| **Memory system** | Vector search, compaction, file-based persistence, silent pre-compaction turns |
| **MCP tools** | Model Context Protocol integration for external tool access |
| **Channel plugins** | WhatsApp, Telegram, Discord, Slack, Signal, Matrix, iMessage, and more |
| **Sandboxing** | Per-agent workspace isolation, read-only modes, tool access control |
| **Cost control** | Per-agent model overrides, token budgets, fallback chains |
| **Health monitoring** | Heartbeat, crash recovery, `openclaw doctor` diagnostics |

---

## 2. What is YAPOC?

YAPOC is a **custom-built, autonomous multi-agent system** inspired by OpenClaw's architecture but implemented from scratch as a Python CLI + backend server. It runs specialized agents with distinct roles, tool sets, and memory — all coordinated by a Master agent.

### Core Philosophy

- **Agent autonomy first** — agents are designed to make decisions, not just execute commands
- **Prompt-as-config** — agent behavior is defined in PROMPT.MD files (same as OpenClaw)
- **CLI + API** — accessed via interactive CLI or web UI, not chat channels
- **Self-evaluating** — built-in meta-cognition via the Evaluator agent
- **Cost-governed** — explicit cost tracking and model optimization

### Key Features

| Feature | Description |
|---------|-------------|
| **Master agent** | Single entry point — decides, delegates, or answers directly |
| **Planning agent** | Task decomposer for complex multi-step work |
| **Builder agent** | File creator/editor, code writer, shell executor |
| **Keeper agent** | Config & secrets guardian (.env, settings, agent-settings.json) |
| **Cron agent** | Scheduled/recurring task manager |
| **Doctor agent** | Autonomous health monitor |
| **Evaluator agent** | Meta-cognition — self-review and issue identification |
| **Librarian agent** | Memory consolidation and archival |
| **Researcher agent** | Web research and deep-dive investigation |
| **Model Manager agent** | Cross-agent model optimization and cost management |
| **Concilium agent** | Multi-stakeholder deliberation for high-risk decisions |
| **Security agent** | Tool-call gatekeeper for policy violations |
| **DAG execution** | Directed-acyclic-graph task orchestration with dependency resolution |
| **Vector memory** | Semantic search across agent memory and session transcripts |
| **Cost governor** | Per-agent token tracking and budget enforcement |
| **Fallback chains** | Multi-provider failover (Anthropic → OpenAI → DeepSeek → local) |
| **Health logging** | Per-agent HEALTH.MD with structured error tracking |
| **Self-evaluation** | Periodic Evaluator reports with ranked issues and proposed fixes |

---

## 3. Architecture Comparison

### High-Level Architecture

```
OpenClaw:                          YAPOC:
┌─────────────────────┐            ┌─────────────────────┐
│   Chat Channels     │            │   CLI / Web UI      │
│ (WhatsApp, Telegram)│            │ (Interactive Shell) │
└─────────┬───────────┘            └─────────┬───────────┘
          │                                  │
┌─────────▼───────────┐            ┌─────────▼───────────┐
│   Gateway Daemon    │            │   Master Agent      │
│ (Routing, Sessions) │            │ (Decision & Delegate)│
└─────────┬───────────┘            └─────────┬───────────┘
          │                                  │
┌─────────▼───────────┐            ┌─────────▼───────────┐
│   Agent Pool        │            │   Agent Pool        │
│ • Agent A (identity)│            │ • Planning          │
│ • Agent B (identity)│            │ • Builder           │
│ • Sub-agents        │            │ • Keeper            │
│ • Agent Teams       │            │ • Researcher        │
└─────────────────────┘            │ • Evaluator         │
                                   │ • Doctor            │
                                   │ • Cron              │
                                   │ • Librarian         │
                                   │ • Concilium         │
                                   └─────────────────────┘
```

### Agent Configuration

| Aspect | OpenClaw | YAPOC |
|--------|----------|-------|
| **Config format** | `openclaw.json` (JSON) | `app/config/agent-settings.json` (JSON) |
| **Agent prompt** | `PROMPT.MD` in agent dir | `PROMPT.MD` in `app/agents/<name>/` |
| **Memory files** | `MEMORY.MD`, `NOTES.MD`, `LEARNINGS.MD` | Same — identical convention |
| **Health tracking** | Heartbeat config in JSON | `HEALTH.MD` per agent |
| **Tool assignment** | Per-agent in `openclaw.json` | Per-agent in `agent-settings.json` |
| **Model binding** | Per-agent in `openclaw.json` | Per-agent in `agent-settings.json` |
| **Fallback chains** | Via model config | Explicit per-agent fallback list |

### Agent Communication

| Aspect | OpenClaw | YAPOC |
|--------|----------|-------|
| **Orchestrator** | Gateway routes messages to agents | Master agent decides and delegates |
| **Sub-agent spawn** | `sessions_spawn` tool | `spawn_agent` tool |
| **Task handoff** | ACP (Agent Control Protocol) | TASK.MD frontmatter + file-based |
| **Parallel execution** | Sub-agents run in isolated sessions | `wait_for_agents` / `execute_dag` |
| **Result retrieval** | Sub-agent announces back to chat | `wait_for_agent` / `read_task_result` |
| **Parent notification** | Agent announces to originating channel | `notify_parent` tool |
| **Peer delegation** | Via ACP or Agent Teams | CONFIG.md `delegation_targets` list |

### Memory & Persistence

| Aspect | OpenClaw | YAPOC |
|--------|----------|-------|
| **Short-term** | Session transcript (JSONL) | Session transcript (JSONL) |
| **Long-term** | MEMORY.MD, NOTES.MD, LEARNINGS.MD | Same files |
| **Vector search** | Built-in, watches memory files | `search_memory` tool with embeddings |
| **Compaction** | Auto-triggered, silent pre-compaction turn | Manual via Librarian agent |
| **Shared knowledge** | Not explicit | `KNOWLEDGE.MD` shared across all agents |
| **Session history** | JSONL per session | `search_memory(scope='sessions')` |

### Scheduling & Automation

| Aspect | OpenClaw | YAPOC |
|--------|----------|-------|
| **Cron** | Built-in Gateway scheduler | Dedicated Cron agent |
| **Health monitoring** | Heartbeat + `openclaw doctor` CLI | Dedicated Doctor agent |
| **Self-evaluation** | Not built-in | Dedicated Evaluator agent |
| **Cost optimization** | Manual config | Dedicated Model Manager agent |
| **Deliberation** | Not built-in | Concilium agent (multi-stakeholder) |

---

## 4. Detailed Comparison Table

| Dimension | OpenClaw | YAPOC |
|-----------|----------|-------|
| **Language** | Go (Gateway) + Python/JS (plugins) | Python (full stack) |
| **Interface** | Chat channels (WhatsApp, Telegram, Discord, etc.) | CLI (REPL) + Web UI |
| **Agent count** | Unlimited (configurable in JSON) | 14 specialized agents (fixed roles) |
| **Agent creation** | Add entry to `openclaw.json` + create dir | `create_agent` tool or manual dir creation |
| **Task decomposition** | Agent Teams / LangGraph-style | Dedicated Planning agent |
| **Code execution** | Via MCP tools or sub-agents | Dedicated Builder agent |
| **Config management** | Manual JSON editing | Dedicated Keeper agent |
| **Web research** | Via MCP browser tools | Dedicated Researcher agent |
| **Memory consolidation** | Auto-compaction | Dedicated Librarian agent |
| **Security** | Sandboxing, workspace access control | Security agent (tool-call gatekeeper) |
| **Cost tracking** | Token budgets in config | Cost governor + Model Manager agent |
| **Self-improvement** | Not built-in | Evaluator agent + LEARNINGS.MD |
| **Decision deliberation** | Not built-in | Concilium agent (multi-agent consensus) |
| **DAG orchestration** | Manual sub-agent chaining | `execute_dag` tool with dependency resolution |
| **Fallback chains** | Model-level fallback | Agent-level fallback (per-agent chains) |
| **Open source** | ✅ MIT License | ✅ Private / experimental |
| **Maturity** | Production-ready (347k+ stars) | Experimental / active development |
| **Community** | Large (docs, plugins, templates) | Single developer |
| **Deployment** | Docker, binary, cloud | Poetry, local Python |

---

## 5. Similarities

Despite different implementations, YAPOC and OpenClaw share deep architectural DNA:

### 1. Prompt-as-Configuration
Both systems define agent behavior through **PROMPT.MD** files. The prompt IS the agent's identity — not code, not a database entry. This makes agent creation a text-editing operation.

### 2. File-Based Memory
Both use the same file convention: `MEMORY.MD` for logs, `NOTES.MD` for structured notes, `LEARNINGS.MD` for learned rules. Memory is durable, inspectable, and portable.

### 3. Master/Sub-Agent Pattern
Both have a **primary orchestrator** (Gateway in OpenClaw, Master in YAPOC) that spawns **sub-agents** for specialized work. Sub-agents run in isolated contexts with their own tools and memory.

### 4. Tool-Based Delegation
Both expose delegation as a **tool call** the agent makes (`sessions_spawn` in OpenClaw, `spawn_agent` in YAPOC). The agent decides when to delegate — it's not hard-coded.

### 5. Fallback Chains
Both support **multi-provider fallback** — if the primary LLM fails, try the next in the chain. This ensures resilience without hard dependency on any single provider.

### 6. Self-Hosted
Both are designed to run on **your own infrastructure**. No cloud dependency, no data leaving your control.

### 7. Cost Awareness
Both provide mechanisms to control costs — per-agent model selection, token limits, and cheaper models for sub-agents.

---

## 6. Key Differences (YAPOC's Innovations)

### 1. Specialized Agent Roles
OpenClaw lets you create any number of generic agents with different prompts. YAPOC defines **fixed, specialized roles** — Builder, Keeper, Doctor, Evaluator, Librarian, Researcher, Concilium — each with curated tools and a specific purpose. This trades flexibility for consistency.

### 2. Meta-Cognition (Evaluator)
YAPOC has an agent whose job is to **evaluate the system itself**. The Evaluator reads health logs, cost data, and task results to identify issues and propose fixes. OpenClaw has no equivalent — health is monitored but not self-diagnosed.

### 3. Deliberation (Concilium)
For high-risk decisions, YAPOC can spawn a **multi-stakeholder deliberation** where counselor agents (architect, security, cost, ethics, user-advocate) debate and reach consensus. OpenClaw has no equivalent — decisions are made by a single agent or the human operator.

### 4. DAG Execution
YAPOC's `execute_dag` tool lets you define a **directed acyclic graph** of agent tasks with automatic dependency resolution and parallel execution. OpenClaw requires manual chaining of sub-agents.

### 5. Complexity Routing
YAPOC's Master agent uses a **formal complexity scale (1-10)** to decide whether to answer directly, delegate to a specialist, route through Planning, or escalate to Concilium. This is a structured decision framework, not ad-hoc.

### 6. Learning System
YAPOC agents maintain **LEARNINGS.MD** files that capture recurring patterns and corrections. Rules are automatically injected into system prompts. OpenClaw relies on the prompt author to update PROMPT.MD manually.

### 7. Shared Knowledge Base
YAPOC has a **shared KNOWLEDGE.MD** that all agents can read — a cross-agent memory for project-wide conventions, discoveries, and decisions. OpenClaw agents are more isolated.

### 8. Channel vs. CLI/UI
OpenClaw is **chat-first** — you talk to agents through WhatsApp, Telegram, etc. YAPOC is **developer-first** — you interact through a CLI shell or web dashboard. This reflects different use cases: OpenClaw for end-user automation, YAPOC for system development and operations.

---

## 7. Design Principles (YAPOC)

### Principle 1: The Master Decides
There is exactly one entry point. The Master agent evaluates every request and decides the best path — direct answer, specialist delegation, planning, or deliberation. No other agent can spawn non-infrastructure agents.

### Principle 2: Complexity Drives Routing
Tasks are routed based on estimated complexity (1-10 scale). Simple tasks go directly to specialists. Complex tasks go through Planning. High-risk decisions go through Concilium. The routing is deterministic and auditable.

### Principle 3: Agents Have Agency
Agents are not function calls — they have their own prompts, tools, memory, and decision-making ability. They can refuse tasks, ask for clarification, and suggest alternatives. Each agent is a miniature autonomous system.

### Principle 4: Self-Evaluation is Built-In
The system regularly evaluates itself. The Evaluator agent identifies issues, ranks them by impact, and proposes fixes. The system learns from corrections via LEARNINGS.MD. This creates a feedback loop for continuous improvement.

### Principle 5: Config is Code-Adjacent
Configuration (agent-settings.json, .env, settings.py) is treated with the same rigor as source code. Changes go through Keeper (not Builder), are validated for correctness, and trigger server restarts to apply.

### Principle 6: Memory is Durable and Searchable
All agent memory is file-based (not ephemeral) and indexed for semantic search. Past decisions, task results, and conversations are retrievable. Nothing is lost on restart.

### Principle 7: Cost is a First-Class Concern
Every agent has a model assignment and fallback chain. Cost tracking is built into the system. The Model Manager agent actively optimizes model assignments to balance capability and cost.

---

## 8. Future Directions

### Short-term
- [ ] **Agent Teams** — formalize multi-agent collaboration patterns (like OpenClaw's Agent Teams)
- [ ] **Channel plugins** — add WhatsApp/Telegram/Discord support (YAPOC as OpenClaw backend)
- [ ] **Session persistence** — full session history with replay capability
- [ ] **Auto-compaction** — automatic memory compaction (like OpenClaw's silent pre-compaction turn)

### Medium-term
- [ ] **Plugin system** — third-party tool and channel plugins
- [ ] **Dashboard UI** — real-time agent monitoring and control
- [ ] **Benchmark suite** — quantitative autonomy scoring
- [ ] **Multi-instance** — run YAPOC agents across multiple servers

### Long-term
- [ ] **Agent marketplace** — share and discover agent configurations
- [ ] **Federated agents** — YAPOC instances that can delegate to each other
- [ ] **Self-modification** — agents that can modify their own prompts and tools (with human approval)

---

## 9. Appendix: Agent Role Summary

| Agent | Role | Spawned By | Delegates To |
|-------|------|------------|--------------|
| **Master** | Entry point, decision maker | User/CLI | All agents |
| **Planning** | Task decomposition | Master | Builder, Keeper |
| **Builder** | Code/file creation | Master, Planning | Keeper |
| **Keeper** | Config & secrets | Master, Planning, Builder | Builder |
| **Cron** | Scheduled tasks | Backend | Builder, Keeper, Doctor, Master |
| **Doctor** | Health monitoring | Backend, Cron | — |
| **Evaluator** | Self-evaluation | Cron | — |
| **Librarian** | Memory consolidation | Master | — |
| **Researcher** | Web research | Master, Planning | — |
| **Model Manager** | Cost optimization | Backend | — |
| **Concilium** | Multi-stakeholder deliberation | Master | Counselor agents |
| **Security** | Tool-call gatekeeper | (inline) | — |

---

*Document generated 2026-05-19. YAPOC v0.x — experimental.*
