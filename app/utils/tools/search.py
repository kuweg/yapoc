"""Search tool — hybrid semantic + keyword search over agent memory."""

from __future__ import annotations

import asyncio
from typing import Any

from app.utils.tools import BaseTool, RiskTier, truncate_tool_output


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "Search agent memory and history using natural language. "
        "Combines semantic similarity (embeddings) with keyword matching "
        "to find relevant past decisions, task results, and notes. "
        "Returns the most relevant entries across all agents (or a specific one)."
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
                "description": "Optional: limit search to a specific agent's memory",
                "default": "",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 8)",
                "default": 8,
            },
        },
        "required": ["query"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        agent = params.get("agent", "") or None
        top_k = params.get("top_k", 8)

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

            results = search_hybrid(query, query_vec, agent=agent, top_k=top_k)

            if not results:
                return f"No results found for query: '{query}'"

            lines: list[str] = [f"Found {len(results)} results for: '{query}'\n"]
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
