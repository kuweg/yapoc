Fix the librarian agent's model and the raw XML tool call issue.

## Problem 1: Model mismatch
The librarian is configured in `app/config/agent-settings.json` with:
- adapter: "deepseek-chat"
- model: "claude-haiku-4-5-20251001"

DeepSeek only accepts model names "deepseek-v4-pro" or "deepseek-v4-flash". Change the librarian's model to "deepseek-v4-flash" (cheaper, faster).

## Problem 2: Raw XML tool calls in RESULT.MD
The librarian's RESULT.MD contains raw tool call XML like:
```
<invoke name="file_read">
<parameter name="path" string="true">some/path</parameter>
</invoke>
```
This happens because the DeepSeek adapter outputs tool calls as raw XML text instead of structured tool events. The fix needs to be in `app/agents/base/__init__.py` in the `run_stream_with_tools` method.

The current sanitization regex at the top of the file (around line 30-40) uses patterns like:
```python
_TOOL_CALL_PATTERN = re.compile(r'<invoke name="([^"]+)"[^>]*>.*?</invoke>', re.DOTALL)
```

But the actual XML in RESULT.MD uses a different format. The fix should:
1. Add a sanitization step in the `finally` block of `run_stream_with_tools` that strips raw XML tool call blocks from the response before writing to RESULT.MD
2. The regex should match `<invoke name="...">...</invoke>` blocks (with any namespace prefix)

## Files to modify:
1. `app/config/agent-settings.json` — change librarian model to "deepseek-v4-flash"
2. `app/agents/base/__init__.py` — add sanitization for raw XML tool calls in the response

## Steps:
1. Read `app/config/agent-settings.json` and find the librarian section
2. Change the model from "claude-haiku-4-5-20251001" to "deepseek-v4-flash"
3. Read `app/agents/base/__init__.py` and find the `run_stream_with_tools` method's `finally` block
4. Add sanitization to strip raw XML tool call blocks from the response before writing to RESULT.MD
5. Verify both changes are correct
