[2026-09-07 23:24] ERROR: OpenAI API error (429): You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1593, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 255, in stream_with_tools
    _raise_with_detail(response)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 80, in _raise_with_detail
    raise httpx.HTTPStatusError(
httpx.HTTPStatusError: OpenAI API error (429): You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.

[2026-09-07 23:24] CONFIG_CHANGE: adapter: 'openai' -> 'google', model: 'gpt-5.6-terra' -> 'gemini-2.5-flash'
