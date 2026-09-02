# Master Health Log

[2026-08-31 23:25] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1393, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 448, in stream_with_tools
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
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1218, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-08-31 23:45] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1300, in run_stream_with_tools
    messages = await self._compact_messages(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1134, in _compact_messages
    summary = await adapter.complete(
              ^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 340, in complete
    response = await client.post(
               ^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1859, in post
    return await self.request(
           ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1540, in request
    return await self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1643, in send
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1637, in send
    await response.aread()
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 979, in aread
    self._content = b"".join([part async for part in self.aiter_bytes()])
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
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
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1218, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-08-31 23:50] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1300, in run_stream_with_tools
    messages = await self._compact_messages(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1134, in _compact_messages
    summary = await adapter.complete(
              ^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 340, in complete
    response = await client.post(
               ^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1859, in post
    return await self.request(
           ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1540, in request
    return await self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1643, in send
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1637, in send
    await response.aread()
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 979, in aread
    self._content = b"".join([part async for part in self.aiter_bytes()])
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
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
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1218, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-08-31 23:56] INFO: Post-restart verification: settings.py confirmed with max_turns=99999 and task_timeout=900 (mid-task stop fix). RESUME.MD empty = clean startup.
[2026-09-01 19:25] INFO: Duplicate-Telegram-message-after-restart: root cause = getUpdates offset not persisted (at-least-once replay on fresh bot with offset=0). Fixed in telegram_bot.py with data/telegram_state.json persistence. Backend restarted.
[2026-09-01 20:11] INFO: Scheduling polish verified + silent-suppression gap fixed in dispatcher.py via builder (execute_dag). 4 cron features confirmed landed in cron_parser.py + main.py _cron_tick. dispatcher.py now suppresses task_complete/morning-report/Telegram for silent jobs; update_queued_task stays unconditional. Import passes (exit 0). Backend restart still needed to load dispatcher.py change — server_restart tool unavailable this session.
[2026-09-01 20:45] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1660, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 984, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 730, in execute
    agent_status = _read_status(agent_name)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1218, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-01 21:31] [STUCK LOOP #1] turn 18 retrying — detected repeated substring ' (done). ... → success\ntask: [Auto-notification via Redis...'
[2026-09-02 08:47] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1300, in run_stream_with_tools
    messages = await self._compact_messages(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1134, in _compact_messages
    summary = await adapter.complete(
              ^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 340, in complete
    response = await client.post(
               ^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1859, in post
    return await self.request(
           ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1540, in request
    return await self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1643, in send
    raise exc
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_client.py", line 1637, in send
    await response.aread()
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/httpx/_models.py", line 979, in aread
    self._content = b"".join([part async for part in self.aiter_bytes()])
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
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
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1218, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

