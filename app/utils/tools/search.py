"""Search tool — hybrid semantic + keyword search over agent memory."""

from __future__ import annotations

import asyncio
from typing import Any

from app.utils.tools import BaseTool, truncate_tool_output


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "Search agent memory and history using natural language. "
        "Combines semantic similarity (embeddings) with keyword matching "
        "to find relevant past decisions, task results, and notes. "
        "Returns the most relevant entries across all agents (or a specific one). "
        "Use `scope='sessions'` to search chat session transcripts instead of agent memory — "
        "useful when you need to recall something said earlier in the current or a past chat."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query (e.g. 'what was decided about authentication')",
            },
            "agent": {
                "type": "string",
                "description": "Optional: limit search to a specific agent's memory (ignored when scope='sessions')",
                "default": "",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 8)",
                "default": 8,
            },
            "scope": {
                "type": "string",
                "description": (
                    "Where to search: 'agent' (default, agent MEMORY/NOTES/LEARNINGS/etc.), "
                    "'sessions' (chat session transcripts), or 'all' (both)."
                ),
                "enum": ["agent", "sessions", "all"],
                "default": "agent",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        agent = params.get("agent", "") or None
        top_k = int(params.get("top_k", 8))
        scope = (params.get("scope") or "agent").lower()
        if scope not in {"agent", "sessions", "all"}:
            scope = "agent"

        try:
            from app.utils.db import init_schema, search_hybrid, get_db
            from app.utils.embeddings import embed

            init_schema()  # ensure tables exist

            # Check if there are any entries
            db = get_db()
            count = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
            if count == 0:
                return "Memory index is empty. No entries have been indexed yet."

            # Embed query in a thread (blocks ~5ms, but model load can be slow on first call)
            query_vec = await asyncio.to_thread(embed, query)

            # Run one or two scoped searches and merge by rrf_score.
            # Session entries live under the pseudo-agent "_session"; agent
            # entries are everything else. Filtering at the search layer is
            # fastest — pulls fewer rows back from SQLite.
            results: list[dict[str, Any]] = []
            if scope in ("agent", "all"):
                agent_hits = search_hybrid(query, query_vec, agent=agent, top_k=top_k)
                # Drop session entries from this branch (defensive; agent=None
                # means "all agents" which includes "_session"). Explicit
                # filter so a user passing agent="" + scope="agent" still
                # gets agent-only results.
                agent_hits = [r for r in agent_hits if r.get("agent") != "_session"]
                results.extend(agent_hits)
            if scope in ("sessions", "all"):
                session_hits = search_hybrid(query, query_vec, agent="_session", top_k=top_k)
                results.extend(session_hits)

            if scope == "all" and results:
                # Merge: drop duplicates by id, sort by rrf_score desc, trim
                seen: set[Any] = set()
                merged: list[dict[str, Any]] = []
                for r in sorted(results, key=lambda x: x.get("rrf_score", 0), reverse=True):
                    key = (r.get("agent"), r.get("source"), r.get("timestamp"), r.get("content", "")[:80])
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(r)
                    if len(merged) >= top_k:
                        break
                results = merged

            if not results:
                return f"No results found for query: '{query}' (scope={scope})"

            lines: list[str] = [f"Found {len(results)} results for: '{query}' (scope={scope})\n"]
            for i, entry in enumerate(results, 1):
                agent_name = entry.get("agent", "?")
                source = entry.get("source", "?")
                ts = entry.get("timestamp", "?")
                content = entry.get("content", "")
                score = entry.get("rrf_score", 0)
                lines.append(
                    f"**{i}. [{agent_name}/{source}] {ts}** (score: {score})\n"
                    f"  {content}\n"
                )

            return truncate_tool_output("\n".join(lines))

        except ImportError:
            return "Error: sentence-transformers not installed. Run: poetry add sentence-transformers"
        except Exception as exc:
            return f"Search error: {exc}"
