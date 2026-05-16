# The History and Architecture of YAPOC

## Origins

YAPOC (Yet Another Python Orchestration Controller) began as an experimental project in early 2026, born from the observation that large language models could be far more effective when organized into specialized, collaborating agents rather than relying on a single monolithic prompt. The first prototype consisted of just three agents — Master, Planner, and Builder — running on a single thread with file-based communication. This triad demonstrated that agent-to-agent handoffs produced measurably better results than a single-agent approach, particularly on multi-step tasks requiring both strategic planning and precise file operations.

## Core Architecture

YAPOC is built on a **hub-and-spoke** architecture with the Master agent at the center. Each agent operates as an independent process with its own system prompt (PROMPT.MD), task queue (TASK.MD), persistent memory (MEMORY.MD), and working notes (NOTES.MD). Agents do not share memory space — all inter-agent communication happens through the file system.

Every agent lives under `app/agents/<name>/` and contains PROMPT.MD (role definition), CONFIG.yaml (model and tool configuration), TASK.MD (frontmatter-driven task queue), MEMORY.MD (episodic log), NOTES.MD (persistent knowledge base), and LEARNINGS.MD (auto-injected learned rules).

## Agent Roles

**Master Agent** — The entry point and orchestrator. It receives user requests, delegates to Planning, and coordinates the overall workflow. It is the only agent that can spawn new dynamic agents.

**Planning Agent** — Decomposes complex tasks into subtasks, determines execution order, and assigns work to appropriate agents.

**Builder Agent** — The file system operator. Creates, edits, reads, and deletes files. Scaffolds new agent directories. Explicitly forbidden from spawning agents.

**Keeper Agent** — Manages configuration files, environment variables, and project settings. The only agent authorized to modify `.env`, `pyproject.toml`, and `settings.py`.

**Cron Agent** — Handles scheduled and recurring tasks. Delegates to Builder, Keeper, Doctor, and Master. Typically assigned a lightweight model for cost efficiency.

**Doctor Agent** — Monitors system health, reviews agent logs (HEALTH.MD, ERROR.MD), and performs diagnostics when agents report errors.

**Librarian Agent** — Manages knowledge by reading, summarizing, and indexing documents. Maintains the shared knowledge base and provides retrieval services via `search_memory`.

## Inter-Agent Communication

Agents communicate exclusively through the file system via **task handoffs**:

1. Agent A writes a task to Agent B's TASK.MD with frontmatter (`status: running`, `assigned_by`, `assigned_at`)
2. Agent B detects the new task, reads it, and begins execution
3. Upon completion, Agent B writes results and calls `notify_parent` to wake Agent A
4. Agent A reads the result and continues

This file-based protocol avoids network dependencies and message brokers. The trade-off is latency, but for YAPOC's task sizes this is negligible.

## Tool System

Each agent is equipped with curated tools: file operations (`file_read`, `file_write`, `file_edit`, `file_delete`), memory tools (`memory_append`, `notes_read`, `notes_write`), agent management (`spawn_agent`, `wait_for_agent`), reporting (`notify_parent`, `health_log`), research (`web_search`, `search_memory`), and utilities (`shell_exec`, `learnings_append`). Tools are assigned per-agent via CONFIG.yaml, and capability modules can be composed for broader functionality.

## Model Strategy

YAPOC uses a tiered model strategy. Master runs claude-sonnet-4-6 for complex orchestration. Cron and Doctor use claude-3-haiku for cost efficiency. Builder and Planner use mid-tier models. All assignments are centralized in `app/config/agent-settings.json` and managed by Keeper.

## Conclusion

YAPOC demonstrates that a file-system-based multi-agent system can be practical, extensible, and cost-effective. By dividing cognitive labor across specialized agents, it achieves results exceeding any single-agent system, while maintaining simplicity through its file-based communication protocol.
