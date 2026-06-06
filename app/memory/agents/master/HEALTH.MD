# Master Health Log

[2026-05-25 23:20] CONFIG_CHANGE: adapter: 'deepseek' -> 'moonshot', model: 'deepseek-chat' -> 'kimi-k2.6'
[2026-05-25 23:35] CONFIG_CHANGE: adapter: 'moonshot' -> 'deepseek', model: 'kimi-k2.6' -> 'deepseek-chat'
[2026-05-25 23:53] [STUCK LOOP #1] turn 106 retrying — detected repeated substring '───────────'
[2026-05-25 23:53] ERROR: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError("OpenAI API error (400): Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.")
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 237, in stream_with_tools
    _raise_with_detail(response)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 67, in _raise_with_detail
    raise httpx.HTTPStatusError(
httpx.HTTPStatusError: OpenAI API error (400): Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1287, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    raise RuntimeError(
RuntimeError: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError("OpenAI API error (400): Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.")

[2026-05-26 10:06] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1547, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 907, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 699, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1133, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-26 10:15] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1287, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/anthropic.py", line 251, in stream_with_tools
    async with self._client.messages.stream(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/lib/streaming/_messages.py", line 317, in __aenter__
    raw_stream = await self.__api_request
                 ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/_base_client.py", line 1992, in post
    return await self.request(cast_to, opts, stream=stream, stream_cls=stream_cls)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anthropic/_base_client.py", line 1712, in request
    response = await self._client.send(
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1629, in send
    response = await self._send_handling_auth(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1657, in _send_handling_auth
    response = await self._send_handling_redirects(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1694, in _send_handling_redirects
    response = await self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1730, in _send_single_request
    response = await transport.handle_async_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_transports/default.py", line 394, in handle_async_request
    resp = await self._pool.handle_async_request(req)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 256, in handle_async_request
    raise exc from None
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 236, in handle_async_request
    response = await connection.handle_async_request(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection.py", line 103, in handle_async_request
    return await self._connection.handle_async_request(request)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 136, in handle_async_request
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 106, in handle_async_request
    ) = await self._receive_response_headers(**kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 177, in _receive_response_headers
    event = await self._receive_event(timeout=timeout)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 217, in _receive_event
    data = await self._network_stream.read(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_backends/anyio.py", line 35, in read
    return await self._stream.receive(max_bytes=max_bytes)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anyio/streams/tls.py", line 244, in receive
    data = await self._call_sslobject_method(self._ssl_object.read, max_bytes)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anyio/streams/tls.py", line 187, in _call_sslobject_method
    data = await self.transport_stream.receive()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/anyio/_backends/_asyncio.py", line 1269, in receive
    await self._protocol.read_event.wait()
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1133, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-31 20:41] ERROR: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError("OpenAI API error (400): Invalid value: 'image'. Supported values are: 'text', 'image_url', 'input_audio', 'refusal', 'audio', and 'file'.")
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

