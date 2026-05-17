# Implementation Plan — Web Browsing & Research Agent (Roadmap #1)

## Context

Per `docs/roadmap.md`, the highest-leverage Phase-2 unlock is a dedicated researcher agent that can both **search** the web and **read** specific pages. Today YAPOC has the search half via `WebSearchTool` (`app/utils/tools/web.py`) but no page-fetch tool — agents can find URLs but can't read them. The researcher agent dir (`app/agents/researcher/`) is fully scaffolded, including a thorough `PROMPT.MD` that already references "read multiple sources" — so the missing piece is the tool, not the agent.

This plan delivers a `fetch_page` tool, wires researcher into the agent registry, and routes master → researcher for research tasks. Scope is intentionally narrow: ship the working loop end-to-end, defer polish (caching, robots.txt, rate limiting) to a follow-up.

## Current state inventory

| Piece | Location | Status |
|---|---|---|
| Researcher agent class | `app/agents/researcher/agent.py` | Done — minimal `BaseAgent` subclass |
| Researcher prompt | `app/agents/researcher/PROMPT.MD` | Done — full role / methodology / output format |
| Researcher CONFIG | `app/agents/researcher/CONFIG.yaml` | Done — adapter/model/tools listed; no `fetch_page` yet |
| `web_search` tool | `app/utils/tools/web.py:10-112` | Done — DuckDuckGo Instant Answer + HTML fallback |
| `fetch_page` tool | — | **Missing** |
| Tool registry entry | `app/utils/tools/__init__.py:180` | Has `web_search`; needs `fetch_page` added |
| Agent-settings binding | `app/config/agent-settings.json` | **Missing `researcher` entry** (master, planning, builder, keeper, cron, doctor, model_manager, librarian are present) |
| Master → researcher delegation | `app/agents/master/CONFIG.yaml` | Master has no `delegation_targets` block — spawn behavior must be verified |
| HTTP client dep | `httpx` (already in `pyproject.toml`) | Done |
| Content-extraction lib | — | **Missing** — add `trafilatura` |

The PROMPT.MD already describes reading pages (line 35) and tells the agent to cite URLs from "actual pages, not just search snippets" (line 80). The prompt is ahead of the toolchain. Adding `fetch_page` closes that gap; no prompt rewrite needed beyond updating the tools list inside the prompt itself.

## Architecture

Master routes research-flavored requests to researcher via the standard `spawn_agent` → TASK.MD → subprocess runner path. The researcher writes findings to `RESULT.MD`; master surfaces them to the user. Researcher's existing prompt already specifies the markdown output structure (executive summary → key findings → details → sources) so no chaining contract needs to be invented.

Researcher already delegates to `builder` and `keeper` (`CONFIG.yaml:20-22`) for complex file writes / config changes — the existing chain `master → researcher → builder` works out of the box.

```
user → master ──spawn_agent("researcher")──→ researcher subprocess
                                              ├─ web_search (existing)
                                              ├─ fetch_page (NEW)
                                              ├─ file_write / notes_*  (existing)
                                              └─ spawn_agent("builder"/"keeper")  (existing)
                                              ↓
                                         RESULT.MD → master → user
```

No changes to the agent runner, dispatcher, or notification system.

## Implementation steps

Apply in this order — each step is independently verifiable.

### Step 1 — Add `trafilatura` dependency

`trafilatura` is the de facto Python library for HTML main-content extraction (Readability-style: strips chrome / nav / ads). Pure Python, MIT, no lxml-system-lib pain, handles utf-8 cleanly.

```
poetry add trafilatura
```

Per project rule: Poetry only, no `pip`. After install, verify `poetry run python -c "import trafilatura; print(trafilatura.__version__)"` works.

### Step 2 — Implement `FetchPageTool` in `app/utils/tools/web.py`

Append a new class after `WebSearchTool` (after line 112). Signature mirrors the existing tool's pattern.

Key design choices, all enforced in the tool:

- **Input**: `{url: str, max_chars?: int = 8000}`. `max_chars` is the cap on extracted text returned to the LLM — prevents one giant page from blowing the context window.
- **URL scheme allowlist**: `http`, `https` only. Reject `file://`, `data:`, `javascript:`, etc. — prevents the LLM from being tricked into reading local files via this tool.
- **Hostname allow list**: skipped in v1. Document constraint in the tool description; revisit if abuse appears.
- **Timeout**: 15 seconds total (network + extraction). Matches the existing fallback search timeout.
- **Redirects**: `follow_redirects=True`, but cap at 5 hops.
- **User-Agent**: `"YAPOC-Researcher/1.0 (+research bot)"`. Honest agent string — many sites block generic curl-style UAs.
- **Content-Type guard**: bail out cleanly if response isn't HTML / text. Return a short message naming the content-type.
- **Extraction**: `trafilatura.extract(html, output_format="markdown", include_links=True, include_images=False, include_tables=True)`. Markdown output preserves headings + links so the agent can cite further.
- **Length cap**: truncate the extracted text at `max_chars`, append `\n\n[truncated — page exceeded max_chars]`.
- **Output**: a single string with header `Page: <final URL after redirects>\nTitle: <title>\n\n<extracted markdown>`.
- **Error path**: return `ERROR: fetch_page failed — <reason>`. Same pattern as `WebSearchTool`.

The tool is stateless — no `_AGENT_DIR_TOOLS` membership.

### Step 3 — Register tool in `TOOL_REGISTRY`

Edit `app/utils/tools/__init__.py:180` (the `web_search` line). Add `"fetch_page": FetchPageTool,` immediately after. Update the import at the top of the file (search for `from .web import WebSearchTool`) to include `FetchPageTool`.

### Step 4 — Add `fetch_page` to researcher's tools list

Edit `app/agents/researcher/CONFIG.yaml:5` — insert `- fetch_page` immediately after `- web_search`. Keep ordering: search → fetch is the natural progression.

### Step 5 — Update researcher's `PROMPT.MD` tools section

`PROMPT.MD:17-28` currently lists tools but omits `fetch_page`. Insert one line:

```
- `fetch_page` — Fetch and read a specific URL, returns extracted main content as markdown
```

Place it between `web_search` and `file_read` (line 18-ish) so the order mirrors `CONFIG.yaml`.

No other prompt edits needed — the methodology section already directs the agent to read pages.

### Step 6 — Add researcher to `app/config/agent-settings.json`

The IDE shows this file open already. Insert a new `"researcher"` block after `"librarian"` (around line 205). Suggested binding mirrors planning/builder style with affordable fallbacks:

```json
"researcher": {
  "adapter": "deepseek",
  "model": "deepseek-chat",
  "tools": [
    "web_search",
    "fetch_page",
    "file_read",
    "file_write",
    "file_list",
    "memory_append",
    "notes_read",
    "notes_write",
    "notes_append",
    "search_memory",
    "shared_knowledge_append",
    "health_log",
    "notify_parent",
    "spawn_agent",
    "wait_for_agent",
    "check_task_status"
  ],
  "temperature": 0.3,
  "max_tokens": 8096,
  "fallbacks": [
    {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
    {"adapter": "openai", "model": "gpt-5.4-mini"},
    {"adapter": "google", "model": "gemini-2.5-flash"}
  ]
}
```

Per CLAUDE.md (`app/agents/CLAUDE.md`): `agent-settings.json` is the authoritative source — when a binding exists there, it wins over `CONFIG.yaml`. Adapter + model + temperature + tools all flow from this file.

### Step 7 — Verify master can spawn researcher

Master's `CONFIG.yaml` has no `delegation_targets` block at all (verified above). Two possibilities:

1. The spawn-authorization check in `SpawnAgentTool` allows spawning when no `delegation_targets` is present (master is exempt by being root).
2. The check is stricter and silently blocks.

**Action**: read `app/utils/tools/delegation.py` (function around `SpawnAgentTool._authorized_to_delegate` or similar). If master needs an explicit allowlist, add `delegation_targets: [planning, builder, keeper, cron, doctor, librarian, researcher, model_manager]` to `app/agents/master/CONFIG.yaml`. If master is exempt, no change.

I'll inspect this during implementation and adjust.

### Step 8 — Smoke test

End-to-end test sequence:

```
poetry run yapoc start
# In the chat UI:
"Research what trafilatura is, what alternatives exist (readability-lxml, newspaper3k), and recommend one. Cite sources."
```

Expected: master spawns researcher; researcher fires 2-3 `web_search` calls, 2-3 `fetch_page` calls, writes a structured findings doc to RESULT.MD, returns to master, master surfaces to user. The final message has named citations with URLs.

Backup smoke test (skip the agent, hit the tool directly):

```
poetry run python -c "
import asyncio
from app.utils.tools.web import FetchPageTool

async def main():
    tool = FetchPageTool()
    print(await tool.execute(url='https://example.com', max_chars=2000))

asyncio.run(main())
"
```

Should print the extracted main content of `example.com`.

## Tool design — `FetchPageTool` specification

| Field | Value |
|---|---|
| `name` | `"fetch_page"` |
| `description` | "Fetch a URL and return the extracted main content as markdown. Use this AFTER web_search to read pages the search returned. Strips navigation/ads/boilerplate. Returns at most `max_chars` characters." |
| `input_schema.properties.url` | string, required |
| `input_schema.properties.max_chars` | integer, default 8000 |
| Allowed schemes | `http`, `https` only |
| HTTP timeout | 15 seconds (network + extraction) |
| Max redirects | 5 |
| User-Agent | `YAPOC-Researcher/1.0 (+research bot)` |
| Output on success | `Page: <final-url>\nTitle: <title>\n\n<markdown>` (truncated at `max_chars`) |
| Output on failure | `ERROR: fetch_page failed — <reason>` |
| Side effects | None — pure HTTP fetch + in-memory extraction |

The tool deliberately does NOT:
- Render JavaScript (no headless browser).
- Follow `robots.txt`.
- Cache results.
- Rate-limit across calls.

These are reasonable v1 omissions; revisit when usage justifies them.

## Verification checklist

- [ ] `poetry run python -c "import trafilatura"` succeeds.
- [ ] `FetchPageTool` exists in `app/utils/tools/web.py`, exported into `TOOL_REGISTRY`.
- [ ] Direct-tool smoke test prints `example.com`'s content.
- [ ] Researcher's `CONFIG.yaml` and `PROMPT.MD` list `fetch_page`.
- [ ] `agent-settings.json` contains a `researcher` block (valid JSON — run `python -m json.tool` to check).
- [ ] Master can spawn researcher (verify via the chat UI prompt above; check `app/agents/researcher/MEMORY.MD` for the new turn).
- [ ] Researcher's `RESULT.MD` contains structured findings with URL citations.
- [ ] Master surfaces those findings to the user.

## Open questions (will decide during implementation, not blockers)

- **Master delegation_targets**: read `SpawnAgentTool` to confirm whether the explicit allowlist is needed.
- **Default model for researcher**: deepseek-chat keeps cost down; anthropic/sonnet would give better synthesis. Sticking with deepseek-chat + anthropic fallback per the existing pattern.
- **`max_chars` default**: 8000 is roughly 2k tokens — fits in any context. Bump to 16000 if the user reports researcher missing detail on long pages.

## Out of scope (explicit non-goals)

- Headless-browser rendering for JS-heavy sites.
- `robots.txt` parsing / per-domain politeness rules.
- Cross-call caching of fetched pages.
- Rate limiting / concurrent-fetch throttling.
- Per-domain credentials / authenticated fetch.
- Frontend surface for researcher (it shows up via the standard agent dashboard already).
- Structured-output / JSON mode for research findings — that's roadmap feature #7, separate plan.
- Researcher persisting findings into vector memory — that's roadmap feature #2's polish step.

## Files to modify / create

| File | Change |
|---|---|
| `pyproject.toml` (+ `poetry.lock`) | Add `trafilatura` |
| `app/utils/tools/web.py` | Add `FetchPageTool` class after `WebSearchTool` |
| `app/utils/tools/__init__.py` | Import `FetchPageTool`; add to `TOOL_REGISTRY` |
| `app/agents/researcher/CONFIG.yaml` | Add `- fetch_page` to tools list |
| `app/agents/researcher/PROMPT.MD` | Add `fetch_page` to tools section |
| `app/config/agent-settings.json` | Add `researcher` block |
| `app/agents/master/CONFIG.yaml` | **Maybe** — only if `SpawnAgentTool` requires explicit `delegation_targets` |

Estimated time: 2–3 hours for someone familiar with the codebase.
