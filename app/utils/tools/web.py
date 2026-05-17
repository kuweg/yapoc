import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from . import BaseTool

_FETCH_PAGE_DEFAULT_MAX_CHARS = 16000
_FETCH_PAGE_TIMEOUT_S = 15.0
_FETCH_PAGE_MAX_REDIRECTS = 5
_FETCH_PAGE_USER_AGENT = "YAPOC-Researcher/1.0 (+research bot)"
_FETCH_PAGE_ALLOWED_SCHEMES = {"http", "https"}


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


class FetchPageTool(BaseTool):
    name = "fetch_page"
    description = (
        "Fetch a URL and return the extracted main content as markdown. "
        "Use this AFTER web_search to read pages the search returned — "
        "search returns snippets, fetch_page returns the actual page text. "
        "Strips navigation, ads, and boilerplate. Returns at most max_chars "
        "characters of extracted content. Only http(s) URLs are allowed; "
        "this tool does NOT render JavaScript, follow robots.txt, or cache."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The http(s) URL to fetch and extract content from.",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Maximum characters of extracted text to return "
                    f"(default: {_FETCH_PAGE_DEFAULT_MAX_CHARS}). Content "
                    f"beyond this is truncated with a marker."
                ),
                "default": _FETCH_PAGE_DEFAULT_MAX_CHARS,
            },
        },
        "required": ["url"],
    }

    async def execute(self, **params: Any) -> str:
        url = str(params.get("url", "")).strip()
        try:
            max_chars = int(params.get("max_chars", _FETCH_PAGE_DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            max_chars = _FETCH_PAGE_DEFAULT_MAX_CHARS
        if max_chars <= 0:
            max_chars = _FETCH_PAGE_DEFAULT_MAX_CHARS

        if not url:
            return "ERROR: fetch_page failed — url is required"

        parsed = urlparse(url)
        if parsed.scheme.lower() not in _FETCH_PAGE_ALLOWED_SCHEMES:
            return (
                f"ERROR: fetch_page failed — only http/https URLs are allowed, "
                f"got scheme {parsed.scheme!r}"
            )
        if not parsed.netloc:
            return "ERROR: fetch_page failed — URL has no host"

        try:
            transport = httpx.AsyncHTTPTransport(retries=0)
            async with httpx.AsyncClient(
                timeout=_FETCH_PAGE_TIMEOUT_S,
                follow_redirects=True,
                max_redirects=_FETCH_PAGE_MAX_REDIRECTS,
                headers={"User-Agent": _FETCH_PAGE_USER_AGENT},
                transport=transport,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                final_url = str(resp.url)
                content_type = resp.headers.get("content-type", "")
                # Be permissive: accept anything that looks like HTML or text.
                ct_lower = content_type.lower()
                if not (
                    "html" in ct_lower
                    or "xml" in ct_lower
                    or ct_lower.startswith("text/")
                    or ct_lower == ""
                ):
                    return (
                        f"ERROR: fetch_page failed — unsupported content-type "
                        f"{content_type!r} for {final_url}"
                    )
                html = resp.text
        except httpx.TimeoutException:
            return f"ERROR: fetch_page failed — timed out after {_FETCH_PAGE_TIMEOUT_S:.0f}s"
        except httpx.TooManyRedirects:
            return f"ERROR: fetch_page failed — too many redirects (> {_FETCH_PAGE_MAX_REDIRECTS})"
        except httpx.HTTPStatusError as exc:
            return f"ERROR: fetch_page failed — HTTP {exc.response.status_code} for {url}"
        except httpx.HTTPError as exc:
            return f"ERROR: fetch_page failed — {exc}"
        except Exception as exc:
            return f"ERROR: fetch_page failed — {exc}"

        # Extract main content via trafilatura. Run in a worker thread —
        # extraction is CPU-bound enough to block the event loop on long pages.
        def _extract(raw_html: str) -> tuple[str, str]:
            import trafilatura

            extracted = trafilatura.extract(
                raw_html,
                output_format="markdown",
                include_links=True,
                include_images=False,
                include_tables=True,
                with_metadata=False,
            ) or ""

            title = ""
            try:
                meta = trafilatura.extract_metadata(raw_html)
                if meta is not None:
                    title = (getattr(meta, "title", "") or "").strip()
            except Exception:
                title = ""
            return extracted, title

        try:
            extracted, title = await asyncio.to_thread(_extract, html)
        except Exception as exc:
            return f"ERROR: fetch_page failed — extraction error: {exc}"

        if not extracted.strip():
            return (
                f"Page: {final_url}\n"
                f"Title: {title}\n\n"
                "[no extractable main content — the page may be JavaScript-only, "
                "behind a login, or otherwise non-extractable]"
            )

        truncated = False
        if len(extracted) > max_chars:
            extracted = extracted[:max_chars]
            truncated = True

        header = f"Page: {final_url}\nTitle: {title}\n\n"
        body = extracted
        if truncated:
            body += f"\n\n[truncated — page exceeded {max_chars} chars]"
        return header + body
