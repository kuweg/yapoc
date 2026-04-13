import asyncio
import json
from typing import Any

import httpx

from . import BaseTool, RiskTier


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo and return a summary of results. "
        "Use this to look up current events, weather, facts, or anything requiring live internet data."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    risk_tier: RiskTier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        max_results = params.get("max_results", 5)

        try:
            import urllib.parse

            encoded_query = urllib.parse.quote(query)
            url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={"User-Agent": "YAPOC-Agent/1.0"})
                resp.raise_for_status()
                data = resp.json()

            parts = []

            # Abstract (instant answer)
            if data.get("AbstractText"):
                parts.append(f"**Summary:** {data['AbstractText']}")
                if data.get("AbstractURL"):
                    parts.append(f"**Source:** {data['AbstractURL']}")

            # Answer (e.g. calculations, conversions)
            if data.get("Answer"):
                parts.append(f"**Answer:** {data['Answer']}")

            # Related topics
            topics = data.get("RelatedTopics", [])
            count = 0
            for topic in topics:
                if count >= max_results:
                    break
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(f"- {topic['Text']}")
                    if topic.get("FirstURL"):
                        parts.append(f"  {topic['FirstURL']}")
                    count += 1

            if not parts:
                # Fallback: try a raw HTML scrape via curl-style search
                return await self._fallback_search(query, max_results)

            return "\n".join(parts)

        except Exception as exc:
            return f"ERROR: Web search failed — {exc}"

    async def _fallback_search(self, query: str, max_results: int) -> str:
        """Fallback: scrape DuckDuckGo HTML search results."""
        try:
            import urllib.parse
            encoded = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                html = resp.text

            # Extract result snippets with a simple regex
            import re
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)

            # Clean HTML tags
            def strip_tags(s: str) -> str:
                return re.sub(r"<[^>]+>", "", s).strip()

            results = []
            for i, (title, snippet) in enumerate(zip(titles, snippets)):
                if i >= max_results:
                    break
                results.append(f"**{strip_tags(title)}**\n{strip_tags(snippet)}")

            if results:
                return f"Search results for: *{query}*\n\n" + "\n\n".join(results)
            return f"No results found for: {query}"

        except Exception as exc:
            return f"ERROR: Fallback search failed — {exc}"
