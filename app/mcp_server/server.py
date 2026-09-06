"""FastMCP stdio server exposing YAPOC as an autonomous backend to MCP clients.

Exposes four tools to an MCP client (e.g. Claude Code launched over stdio):
  yapoc_task       — run an autonomous task on the YAPOC backend (via master)
  yapoc_delegate   — delegate a task to a specific agent
  yapoc_memory     — search backend memory entries
  yapoc_deliberate — run a Concilium deliberation on a plan proposal

Every tool is synchronous on the FastMCP side but delegates to the async HTTP
client via ``asyncio.run``, and wraps failures so the MCP client sees a clean
error string rather than a stack-trace crash.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp_server import backend_client

mcp = FastMCP("yapoc")


def _summarize_task_response(payload: dict) -> str:
    """Render a POST /mcp/run response into a readable string."""
    task_id = payload.get("task_id", "?")
    status = payload.get("status", "?")
    result = payload.get("result")
    error = payload.get("error")
    if status in {"done", None} and result:
        return f"Task {task_id}: DONE\n\n{result}"
    if status in {"timeout", "cancelled"}:
        return (
            f"Task {task_id}: {status.upper()} — task did not reach a terminal "
            "done state before the timeout. Check the YAPOC UI for partial progress."
        )
    if error:
        return f"Task {task_id}: ERROR ({status})\n\n{error}"
    return f"Task {task_id}: status={status} (no result payload)"


@mcp.tool()
async def yapoc_task(goal: str, context: str = "", timeout_s: int = 0) -> str:
    """Run an autonomous task on the YAPOC backend. goal is your instruction; use context for any extra background. execution is delegated to master, which may spawn sub-agents and act on the filesystem. Returns the agent's final result text. timeouts (seconds) only when you expect the task to be long-running."""
    if context and context.strip():
        full = f"[Context]\n{context}\n\n[Task]\n{goal}"
    else:
        full = goal
    try:
        payload = await backend_client.run_task(task=full, timeout_s=timeout_s or None)
        return _summarize_task_response(payload)
    except Exception as exc:  # noqa: BLE001 — must return clean error to MCP client
        return f"yapoc_task error: {exc}"


@mcp.tool()
async def yapoc_delegate(agent: str, task: str, timeout_s: int = 0) -> str:
    """Delegate a task to a named YAPOC agent (e.g. 'builder', 'keeper'). master will spawn that agent, wait for its result, and return that result verbatim. Useful when you want a task handled by a specific team rather than master's own judgement."""
    try:
        payload = await backend_client.run_task(
            task=task, agent=agent, timeout_s=timeout_s or None
        )
        return _summarize_task_response(payload)
    except Exception as exc:  # noqa: BLE001
        return f"yapoc_delegate error: {exc}"


@mcp.tool()
async def yapoc_memory(query: str, agent: str = "", top_k: int = 8) -> str:
    """Search YAPOC's persistent agent-memory index (hybrid keyword+semantic) for past learnings, notes, and outcomes. Useful before acting so you can reuse what YAPOC already knows. agent optionally restricts to one agent's memory. Returns a numbered list of agent / source / content snippets."""
    try:
        data = await backend_client.search_memory(query=query, agent=agent, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        return f"yapoc_memory error: {exc}"

    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        total = data.get("total_indexed", "?") if isinstance(data, dict) else "?"
        return f"No memory matches for {query!r} (total_indexed={total})."

    lines = [f"Memory results for {query!r}:"]
    for i, r in enumerate(results, 1):
        agent_s = (r.get("agent") or "?").strip() or "?"
        source_s = (r.get("source") or "?").strip() or "?"
        content = (r.get("content") or "").strip()
        if len(content) > 300:
            content = content[:297] + "..."
        lines.append(f"{i}. agent={agent_s} | source={source_s}\n   {content}")
    return "\n".join(lines)


@mcp.tool()
async def yapoc_deliberate(proposal: str, max_rounds: int = 3) -> str:
    """Run a YAPOC Concilium deliberation over a plan/proposal text. Multiple counselor agents converge on and verify the plan over a bounded number of rounds, producing an approved plan, conditions, blockers, or an escalation. Use when a proposal is risky or needs multi-agent review before you commit to it."""
    try:
        data = await backend_client.deliberate(proposal=proposal, max_rounds=max_rounds)
    except Exception as exc:  # noqa: BLE001
        return f"yapoc_deliberate error: {exc}"

    if not isinstance(data, dict):
        return f"Unexpected deliberation response: {data!r}"

    session_id = data.get("session_id", "?")
    status = data.get("status") or data.get("state") or "?"
    if status == "still_running":
        return (
            f"Deliberation {session_id} is STILL RUNNING. "
            f"Poll /concilium/result/{session_id} for the final result."
        )

    parts = [f"Deliberation {session_id}: final status={status}"]
    if data.get("plan"):
        parts.append(f"\nApproved plan:\n{data['plan']}")
    if data.get("conditions"):
        parts.append(f"\nConditions ({len(data['conditions'])}):\n- " + "\n- ".join(str(c) for c in data["conditions"]))
    if data.get("blockers"):
        parts.append(f"\nBlockers ({len(data['blockers'])}):\n- " + "\n- ".join(str(b) for b in data["blockers"]))
    es = data.get("escalation_summary")
    if isinstance(es, dict):
        parts.append(f"\nEscalation: {es.get('recommendation', 'see result for details')}")
    rec = data.get("recommendation")
    if rec:
        parts.append(f"\nRecommendation: {rec}")
    return "\n".join(parts)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
