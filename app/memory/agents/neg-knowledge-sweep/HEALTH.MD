[2026-09-08 00:07] ERROR: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.adaptive.budget_tokens: Extra inputs are not permitted'}, 'request_id': 'req_011CepqfVPXaiSDHhWgPXUiC'}
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1593, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/anthropic.py", line 251, in stream_with_tools
    async with self._client.messages.stream(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/lib/streaming/_messages.py", line 317, in __aenter__
    raw_stream = await self.__api_request
                 ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/_base_client.py", line 1992, in post
    return await self.request(cast_to, opts, stream=stream, stream_cls=stream_cls)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/_base_client.py", line 1777, in request
    raise self._make_status_error_from_response(err.response) from None
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'thinking.adaptive.budget_tokens: Extra inputs are not permitted'}, 'request_id': 'req_011CepqfVPXaiSDHhWgPXUiC'}

