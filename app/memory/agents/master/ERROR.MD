[ERROR] All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError("OpenAI API error (400): Invalid value: 'image'. Supported values are: 'text', 'image_url', 'input_audio', 'refusal', 'audio', and 'file'.")

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 237, in stream_with_tools
    _raise_with_detail(response)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 67, in _raise_with_detail
    raise httpx.HTTPStatusError(
httpx.HTTPStatusError: OpenAI API error (400): Invalid value: 'image'. Supported values are: 'text', 'image_url', 'input_audio', 'refusal', 'audio', and 'file'.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1287, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    raise RuntimeError(
RuntimeError: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError("OpenAI API error (400): Invalid value: 'image'. Supported values are: 'text', 'image_url', 'input_audio', 'refusal', 'audio', and 'file'.")
