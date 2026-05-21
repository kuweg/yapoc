"""Browser tool — fetch JS-rendered pages using Playwright headless Chromium.

Unlike fetch_page (which uses httpx + trafilatura and can't execute JS),
this tool launches a real headless browser, waits for the page to fully
render, and returns the extracted text content.

Use this for JavaScript SPAs (React, Vue, Angular) where fetch_page returns
empty or skeleton HTML. For static/SSR pages, prefer fetch_page — it's 10x
faster and has no browser dependency.

Registered as `fetch_page_js` in app/utils/tools/__init__.py.
"""
from __future__ import annotations

from typing import Any

from . import BaseTool


class FetchPageJsTool(BaseTool):
    name = "fetch_page_js"
    description = (
        "Fetch a JavaScript-rendered page using a headless Chromium browser. "
        "Use this for SPAs (React/Vue/Angular) where fetch_page returns empty content. "
        "Slower than fetch_page (~3-5s) but works on any JS-rendered page. "
        "Returns extracted main content as markdown text. "
        "Only use when fetch_page fails or returns skeleton HTML."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The http(s) URL to fetch and render.",
            },
            "wait_for_selector": {
                "type": "string",
                "description": (
                    "Optional CSS selector to wait for before extracting content. "
                    "E.g. '.leaderboard-table' or '#results'. "
                    "If not provided, waits for networkidle."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Max milliseconds to wait for page load (default: 15000).",
                "default": 15000,
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of extracted text to return (default: 16000).",
                "default": 16000,
            },
        },
        "required": ["url"],
    }

    async def execute(self, **params: Any) -> str:
        url = str(params.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return "ERROR: Only http(s) URLs are supported."

        wait_for_selector = params.get("wait_for_selector", "")
        timeout = int(params.get("timeout", 15000))
        max_chars = int(params.get("max_chars", 16000))

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return (
                "ERROR: Playwright is not installed. "
                "Run: poetry add playwright && poetry run playwright install chromium"
            )

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    # Set a realistic user agent to avoid bot detection
                    await page.set_extra_http_headers({
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        )
                    })

                    # Navigate to the URL
                    await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

                    # Wait for specific selector or networkidle
                    if wait_for_selector:
                        try:
                            await page.wait_for_selector(
                                wait_for_selector, timeout=timeout
                            )
                        except Exception:
                            pass  # selector didn't appear — extract what we have
                    else:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=min(timeout, 8000))
                        except Exception:
                            pass  # networkidle timeout — extract what we have

                    # Get page title
                    title = await page.title()

                    # Extract text content using trafilatura on the rendered HTML
                    html = await page.content()
                    try:
                        import trafilatura
                        text = trafilatura.extract(
                            html,
                            include_tables=True,
                            include_links=False,
                            no_fallback=False,
                        ) or ""
                    except Exception:
                        # Fallback: extract innerText directly
                        text = await page.evaluate("() => document.body.innerText") or ""

                    if not text.strip():
                        # Last resort: get all visible text
                        text = await page.evaluate(
                            "() => Array.from(document.querySelectorAll('body *'))"
                            ".filter(el => el.children.length === 0 && el.textContent.trim())"
                            ".map(el => el.textContent.trim()).join('\\n')"
                        ) or ""

                    result = f"# {title}\n\n{text}" if title else text
                    if len(result) > max_chars:
                        result = result[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"

                    return result or "ERROR: Page rendered but no text content could be extracted."

                finally:
                    await browser.close()

        except Exception as exc:
            return f"ERROR: fetch_page_js failed: {exc}"
