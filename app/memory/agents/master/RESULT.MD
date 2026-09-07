The image analysis is now complete — the vision pipeline is fixed and working.

## What the image shows

It's a screenshot of the **YAPOC web UI** (dark theme, `localhost:5173`) showing:

- **Left panel** — the AGENTS list, all IDLE (master, builder, planning, evaluator, etc.), with "Open Logs", "Spawn"/"Kill" buttons, and a topology section.
- **Top nav** — CHAT, AGENTS, TASKS, INSIGHTS, OBS, CONCILIUM, MEMORY, VAULT, SESSIONS, CHANNELS, SKILLS, + NEW.
- **Main chat log** — a conversation about building the **in-chat file/artifact viewer sidebar**: the user reported a "Not Found" link, and master walked through fixing the broken artifact route and adding a right-side file preview pane (text/image/PDF/download, mobile full-screen overlay, 8/8 backend tests passed, frontend build passed).
- **Right panel** — a `document_processor_test.md` preview showing "Not Found" + a Download button, plus some unrelated window-manager settings (keyboard swap, window aspect, pin-to-hotkey, look & feel).
- **Bottom bar** — "0 running", "4 active links", "5 error", "LIVE".

## What I had to fix to get here

The image analysis was failing for a real reason, not a flaky one. Three issues, all now resolved:

1. **`document_processor` was pointed at OpenAI** (`gpt-5.6-terra`), which is out of credits (429). Switched it to `gemini-2.5-flash`.
2. **The Gemini adapter silently dropped image blocks.** The base agent reformats `image_read` results into an Anthropic-style `{"type":"image","source":{...}}` block, but the Gemini adapter's `_messages_to_contents` had no branch for it — so the base64 was stuffed into a `function_response` as raw text (~270K tokens of base64 the model couldn't "see").
3. **The image block is nested inside `tool_result.content`**, not top-level, so a naive top-level `image` branch wouldn't fire.

I added a `_extract_image_parts` helper to `app/utils/adapters/google.py` that detects nested image blocks in `tool_result` content and emits them as proper Gemini `types.Part.from_bytes(...)` inline-data parts. Verified with a direct unit test (image part emitted correctly), and restarted the backend to apply it.

The result above is the first successful vision pass through the Gemini path — the model actually read the screenshot and transcribed the chat log, agent list, and settings panel in detail.