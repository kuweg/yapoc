I'll start by researching the actual repo state to understand the current code structure before decomposing this task. Let me investigate the key files mentioned in the architecture facts.Now let me investigate the backend structure — the tools registry, dispatcher, routers, and the gate file's message assembly mechanism.Let me look at the tools registry, dispatcher, and how tools are registered. Let me also look at the main.py and how routers are registered.The dispatcher handles the task execution and message assembly. This is where the final message parts are assembled. Let me look at how the master agent assembles messages and where the SSE/websocket message with `parts` is constructed. Let me look at the master agent and how messages flow. Let me examine the master agent's `handle_task_stream` and how parts get attached.

Let me look at the master agent and the base agent's message assembly, plus how the frontend receives structured messages with parts.Let me look at the master agent and how it emits messages with parts. Let me search for where `parts` is constructed in the backend and how the SSE stream carries structured parts.Now I need to understand how the frontend receives structured messages with `parts`. The dispatcher pushes `task_complete` events with `messages` (text blocks). But where do the `parts` (tool calls, thinking) come from? Let me look at how the SSE/websocket stream carries parts and how the frontend assembles messages. Let me look at the base agent's `run_stream_with_tools` and `_emit_event`, plus the websocket relay.

Let me check the base agent `__init__.py` (the gate file) to understand `_emit_event` and how parts are assembled, and how the frontend gets `parts`.This is a large gate file. I need to understand how the frontend receives structured messages with `parts`. The dispatcher pushes `task_complete` events with plain text `messages`. But the frontend `Message` type has `parts`. Let me understand where the frontend assembles messages with parts from the SSE stream.

Let me look at how the frontend consumes the stream and builds messages with parts. Let me search the frontend for where parts are assembled from stream events.Let me look at how the frontend assembles messages with parts from the stream. This is critical to understand where chart parts would flow. Let me look at the chat store and useStream hook.Let me find where the SSE stream events are consumed and turned into messages with `parts`. Let me look at the ChatPanel and the session store.Now I need to find where the SSE stream events are consumed and turned into messages with `parts`. Let me look at the ChatPanel which likely handles the streaming and message assembly.This is a large file. I have enough understanding of the frontend architecture now. Let me continue reading the rest of ChatPanel to understand how the final message is assembled and where a chart part would need to be attached. Let me read the rest of the file focusing on the message completion logic.Now I have a very clear understanding of the frontend architecture. This is a critical finding:

**The frontend chat flow does NOT receive structured `parts` from the backend SSE stream.** The `task_complete`/`task/stream` events only carry plain text deltas (`text` events). The `parts` array is **assembled entirely client-side** in `ChatPanel.tsx` from the streamed `thinking`, `text`, `tool_start`, `tool_done`, `compact` events.

This is a crucial architectural insight that changes the plan. Let me verify by checking the backend task stream endpoint and how it emits events. Let me look at the dispatcher and the task stream router.

Let me check how the SSE `/api/task/stream` endpoint works and what events it emits.Let me look at the task stream router and how the SSE events are emitted to the frontend for a chat turn. Let me look at the tasks router and the `_execute_task` in dispatcher.Now I have a complete picture. This is a **critical architectural finding** that changes the plan significantly.

## Key Finding: The chat stream carries NO structured parts

The `/api/task/stream` SSE endpoint emits only these event types (via `_event_to_dict`):
- `thinking`, `text`, `tool_start`, `tool_done`, `compact`, `usage_stats`, `status`, `error`, `attachments`, `keepalive`

There is **no `chart` event type**, and the frontend `ChatPanel.tsx` assembles `parts` **entirely client-side** from these streamed events. The `parts` array is never sent from the backend for the interactive chat flow.

So the architectural direction in the task says: "the option is attached as a `chart` part at message-completion time" and "the mechanism to attach the chart part to the final message must live OUTSIDE app/agents/base/__init__.py — e.g. in the dispatcher or a helper that post-processes the final assistant message."

But the reality is: **the dispatcher does NOT assemble the final message parts for the chat flow.** The chat flow is a live SSE stream where the frontend builds parts from deltas. The dispatcher's `_execute_task` (for background tasks) assembles `message_blocks` from text deltas, but the chat `/task/stream` path streams raw events directly.

This means for a chart to appear in the interactive chat, we need a **new SSE event type** (`chart`) that the frontend can consume and turn into a `chart` part. But the task says charts must be attached at message-completion time, NOT via a new streaming event type in the gate file.

Let me reconcile this. The gate file `app/agents/base/__init__.py` contains `_emit_event()`. The task says charts must NOT be pushed via a new streaming event type in the gate file. But the frontend needs to receive chart data somehow.

Let me reconsider. The cleanest approach that respects the constraint:

**The `render_chart` tool is called by master. Its tool_result carries the ECharts option JSON.** The frontend already receives `tool_done` events with `result` strings. So the chart option is already flowing to the frontend as part of the tool trace.

But the task wants the chart rendered as a **visible chart part**, not buried in a tool call trace. 

Given the architecture, the realistic integration points are:

**Option A (backend SSE event):** Add a `chart` event type to the SSE stream. But this requires either editing the gate file (forbidden) OR adding a new event type in `tasks.py` `_event_to_dict` + a new event emitted somewhere. The gate file `_emit_event` only emits text/thinking/tool events. We can't add a chart emit there.

**Option B (frontend post-processing of tool_result):** When master calls `render_chart`, the tool_done event carries the option JSON in `result`. The frontend `ChatPanel` already receives `tool_done`. We could have the frontend detect a `render_chart` tool_done and render a chart block. But this mixes concerns and the tool trace is collapsible.

Let me reconsider the actual cleanest path given constraints. Let me re-read the task's architectural direction carefully:

> "Then at message-completion time the option is attached as a `chart` part. IMPORTANT: because the gate file can't be edited by builder, the mechanism to attach the chart part to the final message must live OUTSIDE app/agents/base/__init__.py — e.g. in the dispatcher (`app/backend/dispatcher.py`) or a helper that post-processes the final assistant message. Investigate where the final message parts are assembled and hook chart attachment there."

The task author assumed the dispatcher assembles final message parts. My investigation shows that for the **interactive chat** flow, parts are assembled client-side. For **background tasks** (dispatcher `_execute_task`), the dispatcher assembles `message_blocks` from text deltas and pushes `task_complete` events.

Given this reality, I need to report back to master with the exact finding and the hook needed. This is exactly the scenario the task anticipated: "If chart attachment to the final message requires a hook there, STOP and report back to master with the exact hook needed."

Actually, let me reconsider. The task anticipated needing a gate-file hook. But my finding is different and arguably more important: **the interactive chat stream doesn't carry structured parts at all**, so attaching a chart part "at message completion" in the dispatcher won't reach the interactive chat — it would only reach background task completions.

Let me verify the dispatcher's `_execute_task` message assembly to understand the background path fully, and confirm the chat path truly has no parts.

Let me look at the dispatcher `_execute_task`.I now have a complete and definitive understanding of the architecture. Let me confirm my key finding and then report back to master.

## Definitive Architecture Finding

The interactive chat flow (`POST /api/task/stream` → `ChatPanel.tsx`) is a **live SSE stream of primitive deltas** (`text`, `thinking`, `tool_start`, `tool_done`, `compact`). The frontend assembles `parts` **entirely client-side** in `ChatPanel.tsx` via `applyPendingEvents()`. **The backend never sends a structured `parts` array for the interactive chat.**

The dispatcher's `_execute_task` (background tasks) assembles `message_blocks` from text deltas only — it does NOT carry tool parts either.

This means the architectural direction's assumption — "attach the chart part to the final message in the dispatcher at message-completion time" — **does not hold for the interactive chat**. A chart attached in the dispatcher would only appear in background task completions, not in the live chat where the user asks "how much money did I burn?".

For a chart to appear in the interactive chat, the chart data must flow over the SSE stream as a **new event type** that the frontend can consume and turn into a `chart` part. This requires:
1. A new SSE event type (e.g. `chart`) emitted from the backend.
2. `_event_to_dict` in `tasks.py` to serialize it.
3. Frontend `ChatPanel` to handle a `chart` event and append a `chart` part.

The constraint says charts must NOT be pushed via a new streaming event type **in the gate file** (`app/agents/base/__init__.py`). But the gate file's `_emit_event()` is what pushes events during the agent run. The `render_chart` tool's result flows through the normal tool mechanism.

Let me think about the cleanest approach that respects ALL constraints:

**The `render_chart` tool is called by master mid-turn.** Its `tool_result` (containing the ECharts option JSON) is emitted by the gate file's `_emit_event` as a normal `tool_result`/`tool_done` event — this is already happening and doesn't require gate-file edits. The frontend already receives `tool_done` events with the `result` string.

So the chart option **already reaches the frontend** as part of the tool trace. The question is purely about **rendering it as a visible chart** rather than burying it in a collapsible tool call.

Given the constraint that we cannot edit the gate file and cannot add a new streaming event type there, but the frontend DOES receive the `render_chart` tool_done result — the cleanest path is:

**Frontend-side: In `ChatPanel.tsx`, when a `tool_done` event for tool name `render_chart` arrives, parse the option JSON from its result and append a `chart` part** (in addition to / instead of the tool trace). This requires:
- Adding `chart` to the TaskPart union in `api/types.ts`
- Handling `chart` in `applyPendingEvents` (ChatPanel) — detect `render_chart` tool_done → append chart part
- Handling `chart` in `groupParts.ts`
- Rendering `chart` in `MessageBubble`/`PartsChain` via a `ChartBlock` component
- Installing `echarts`

This is fully client-side chart attachment from the tool result — no gate-file edit, no new backend streaming event. It satisfies "charts attached at message-completion time" in the sense that the chart part is appended when the tool completes (which is during the message assembly on the client).

Wait — but the task explicitly says the mechanism to attach the chart part should live in the dispatcher or a backend helper. However, my investigation proves that's architecturally wrong for the chat flow. The task also says: "If chart attachment to the final message requires a hook there, STOP and report back to master with the exact hook needed."

Given the significant divergence between the task's architectural assumption and the verified reality, and given this is a cross-cutting feature where getting the integration point wrong wastes builder effort, I should report this finding back to master with a clear recommendation before executing. This is the "Uncertainty Protocol" / "Conflict Detection" situation — the surface instruction (attach in dispatcher) conflicts with the verified architecture (chat parts are client-assembled).

However, I can still make substantial progress on the parts that are unambiguous and don't depend on the integration-point decision:
1. **Frontend**: install `echarts`, add `chart` to TaskPart union, create `ChartBlock` component, handle in `groupParts.ts` and `MessageBubble`/`PartsChain`. These are needed regardless of how the chart part arrives.
2. **Backend**: `render_chart` tool + registry entry, `reports.py` router. These are needed regardless.
3. The **integration point** (how chart parts get into the live chat message) is the decision that needs master's input.

Let me reconsider whether I should just proceed with the client-side tool_done approach since it's the only viable one that respects the gate-file constraint, OR report back first.

Given the task's explicit instruction to STOP and report if a gate-file hook is needed, and given my finding that the dispatcher-attachment approach won't work for the chat flow, I think the right move is to report this architectural finding to master with a concrete recommendation, while noting that I can proceed with the unambiguous parts (tool, router, frontend rendering) in parallel.

Actually, let me reconsider the scope. The task is large and cross-cutting. Let me be pragmatic: I'll report the critical finding to master and recommend the client-side tool_done integration approach, and ask whether to proceed with that. But I can also note that the frontend rendering + backend tool/router work is needed regardless and I can start it.

Given the guidance to prefer direct action on reversible/safe changes, and that the frontend rendering components + backend tool/router are needed under ANY integration approach, I'll proceed to implement those unambiguous parts while reporting the integration-point finding to master.

Actually, let me reconsider once more. The cleanest and most robust design given the constraint is actually a **hybrid**:

The `render_chart` tool returns a normalized ECharts option. When master calls it, the tool_done event streams to the frontend with the option JSON in `result`. The frontend detects `render_chart` tool_done and renders a chart. This is clean, requires no gate-file edit, no new backend event, and works for the live chat.

But there's a subtlety: tool_done events are part of the collapsible execution trace. If we want the chart as a first-class visible part, the frontend needs to distinguish "this render_chart tool_done should produce a visible chart" from the trace. We can do this by having the frontend, upon a `render_chart` tool_done, append a `chart` part AND skip showing it as a plain tool call (or show both). 

Let me verify the tool_done event carries the full result. From `_event_to_dict`: `ToolDone` → `{"type": "tool_done", "name": event.name, "result": event.result, "is_error": event.is_error}`. And the frontend `applyPendingEvents` handles `tool_done` by finding the matching open tool part and setting its result. So yes, the result string is available.

This is the right approach. Let me now decide: proceed with implementation or report first?

I'll report the finding to master AND proceed with the unambiguous implementation in parallel. Actually, since notify_parent is my completion mechanism and I shouldn't partially complete, let me think about whether to do the full build now.

Given the size and that the integration approach (client-side tool_done detection) is a deviation from the stated architectural direction (dispatcher attachment), I should get master's confirmation on the integration point before doing the full build. But I can do the parts that are unambiguous.

Let me be decisive. I'll report the architectural finding to master with a clear recommendation, and note that I'm proceeding with the unambiguous backend + frontend-rendering work. But since I need to coordinate via builder and this is a big build, let me first check the current state of the relevant files to make sure I understand exactly what to delegate.

Let me look at the tools registry structure and an example tool to understand how to add `render_chart`, and check the MessageBubble/groupParts/types files fully.

Let me read the key files I'll need to modify.