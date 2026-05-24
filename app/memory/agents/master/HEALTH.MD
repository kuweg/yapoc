# Master Health Log

[2026-05-19 23:19] INFO: HEALTH.MD cleared — historical timeout errors archived. Root cause: DeepSeek API streaming stalls. Fix applied: added 60s per-chunk timeout to stream() method in deepseek.py. See app/agents/master/MEMORY.MD for full investigation.
[2026-05-20 08:27] ERROR: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': '* GenerateContentRequest.contents[2].parts[0].function_response.name: Name cannot be empty.\n* GenerateContentRequest.contents[2].parts[1].function_response.name: Name cannot be empty.\n', 'status': 'INVALID_ARGUMENT'}}
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1180, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/google.py", line 242, in stream_with_tools
    stream = await self._client.aio.models.generate_content_stream(
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/models.py", line 8649, in generate_content_stream
    response = await self._generate_content_stream(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/models.py", line 7135, in _generate_content_stream
    response_stream = await self._api_client.async_request_streamed(
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/_api_client.py", line 1672, in async_request_streamed
    response = await self._async_request(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/_api_client.py", line 1588, in _async_request
    return await self._async_retry(  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/asyncio/__init__.py", line 112, in __call__
    do = await self.iter(retry_state=retry_state)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/asyncio/__init__.py", line 157, in iter
    result = await action(retry_state)
             ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/_utils.py", line 111, in inner
    return call(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/__init__.py", line 413, in exc_check
    raise retry_exc.reraise()
          ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/__init__.py", line 184, in reraise
    raise self.last_attempt.result()
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/concurrent/futures/_base.py", line 449, in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/concurrent/futures/_base.py", line 401, in __get_result
    raise self._exception
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/tenacity/asyncio/__init__.py", line 116, in __call__
    result = await fn(*args, **kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/_api_client.py", line 1492, in _async_request_once
    await errors.APIError.raise_for_async_response(client_response)
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/errors.py", line 247, in raise_for_async_response
    await cls.raise_error_async(status_code, response_json, response)
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/google/genai/errors.py", line 269, in raise_error_async
    raise ClientError(status_code, response_json, response)
google.genai.errors.ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': '* GenerateContentRequest.contents[2].parts[0].function_response.name: Name cannot be empty.\n* GenerateContentRequest.contents[2].parts[1].function_response.name: Name cannot be empty.\n', 'status': 'INVALID_ARGUMENT'}}

[2026-05-22 00:26] ERROR: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError('OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 173973, Requested 34956. Please try again in 2.678s. Visit https://platform.openai.com/account/rate-limits to learn more.')
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 230, in stream_with_tools
    _raise_with_detail(response)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 66, in _raise_with_detail
    raise httpx.HTTPStatusError(
httpx.HTTPStatusError: OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 173973, Requested 34956. Please try again in 2.678s. Visit https://platform.openai.com/account/rate-limits to learn more.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1180, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    raise RuntimeError(
RuntimeError: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError('OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 173973, Requested 34956. Please try again in 2.678s. Visit https://platform.openai.com/account/rate-limits to learn more.')

[2026-05-22 00:27] ERROR: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError('OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 174062, Requested 35911. Please try again in 2.991s. Visit https://platform.openai.com/account/rate-limits to learn more.')
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 230, in stream_with_tools
    _raise_with_detail(response)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/openai.py", line 66, in _raise_with_detail
    raise httpx.HTTPStatusError(
httpx.HTTPStatusError: OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 174062, Requested 35911. Please try again in 2.991s. Visit https://platform.openai.com/account/rate-limits to learn more.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1180, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    raise RuntimeError(
RuntimeError: All 4 adapters in the fallback chain failed to start streaming tools. Last error: HTTPStatusError('OpenAI API error (429): Rate limit reached for gpt-5.4-mini in organization org-L0BK9AeFQFz2GhldzVnS0yEY on tokens per min (TPM): Limit 200000, Used 174062, Requested 35911. Please try again in 2.991s. Visit https://platform.openai.com/account/rate-limits to learn more.')

[2026-05-23 13:14] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1434, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 813, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 686, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1039, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 13:36] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1201, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 276, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/moonshot.py", line 315, in stream_with_tools
    async with client.stream(
               ^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/contextlib.py", line 210, in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1583, in stream
    response = await self.send(
               ^^^^^^^^^^^^^^^^
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1052, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 13:36] INFO: Cross-agent timeout root-cause identified and fixed. Planning task_timeout increased 300→600s to prevent cascading timeout collision with builder.
[2026-05-23 13:41] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1201, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 301, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/moonshot.py", line 329, in stream_with_tools
    line = await aiter_lines.__anext__()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1031, in aiter_lines
    async for text in self.aiter_text():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1018, in aiter_text
    async for byte_content in self.aiter_bytes():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 997, in aiter_bytes
    async for raw_bytes in self.aiter_raw():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1055, in aiter_raw
    async for raw_stream_bytes in self.stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 176, in __aiter__
    async for chunk in self._stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_transports/default.py", line 271, in __aiter__
    async for part in self._httpcore_stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 407, in __aiter__
    raise exc from None
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 403, in __aiter__
    async for part in self._stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 342, in __aiter__
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 334, in __aiter__
    async for chunk in self._connection._receive_response_body(**kwargs):
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 203, in _receive_response_body
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1052, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 13:46] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1201, in run_stream_with_tools
    _ts = _time.strftime("%Y-%m-%d %H:%M", _time.localtime())
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 301, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/moonshot.py", line 329, in stream_with_tools
    line = await aiter_lines.__anext__()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1031, in aiter_lines
    async for text in self.aiter_text():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1018, in aiter_text
    async for byte_content in self.aiter_bytes():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 997, in aiter_bytes
    async for raw_bytes in self.aiter_raw():
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 1055, in aiter_raw
    async for raw_stream_bytes in self.stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 176, in __aiter__
    async for chunk in self._stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_transports/default.py", line 271, in __aiter__
    async for part in self._httpcore_stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 407, in __aiter__
    raise exc from None
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/connection_pool.py", line 403, in __aiter__
    async for part in self._stream:
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 342, in __aiter__
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 334, in __aiter__
    async for chunk in self._connection._receive_response_body(**kwargs):
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpcore/_async/http11.py", line 203, in _receive_response_body
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1052, in run_stream_with_tools
    )
      
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 18:40] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1506, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 869, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 686, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1095, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 18:52] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1506, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 869, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 686, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1095, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.pyenv/versions/3.12.8/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-05-23 23:40] [STUCK LOOP #1] turn 9 retrying — detected repeated substring '              '
[2026-05-23 23:40] [STUCK LOOP #2] turn 11 retrying — detected repeated substring '             '
