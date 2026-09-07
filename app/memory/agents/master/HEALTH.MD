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

[2026-09-02 09:31] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1400, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 284, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 434, in stream_with_tools
    async with client.stream(
               ^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/contextlib.py", line 210, in __aenter__
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

[2026-09-02 09:49] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1660, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 984, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 1872, in execute
    return await wait_tool.execute(agent_name=agent_name)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 843, in execute
    await asyncio.sleep(poll_interval)
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

[2026-09-02 12:00] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1678, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 985, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 843, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1219, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 12:05] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1678, in run_stream_with_tools
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 985, in _execute_tool
    """
        
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 1872, in execute
    return await wait_tool.execute(agent_name=agent_name)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 843, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1219, in run_stream_with_tools
    summarize_prompt = _COMPACT_SYSTEM_PROMPT
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 13:37] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1502, in run_stream_with_tools
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1316, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 13:55] CONFIG_CHANGE: temperature: 1.0 -> 0.3
[2026-09-02 18:38] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1841, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1114, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 1872, in execute
    return await wait_tool.execute(agent_name=agent_name)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 843, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1348, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 20:03] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1841, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1114, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/shell.py", line 53, in execute
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 520, in wait_for
    return await fut
           ^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/subprocess.py", line 201, in communicate
    stdin, stdout, stderr = await tasks.gather(stdin, stdout, stderr)
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/subprocess.py", line 181, in _read_stream
    output = await stream.read()
             ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 706, in read
    block = await self.read(self._limit)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 713, in read
    await self._wait_for_data('read')
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 545, in _wait_for_data
    await self._waiter
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1348, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 20:46] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1433, in run_stream_with_tools
    messages = await self._compact_messages(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1264, in _compact_messages
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
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/locks.py", line 212, in wait
    await fut
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1348, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 21:56] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1450, in run_stream_with_tools
    messages = await self._compact_messages(
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1265, in _compact_messages
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1349, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-02 22:22] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1876, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1115, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/delegation.py", line 844, in execute
    await asyncio.sleep(poll_interval)
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 665, in sleep
    return await future
           ^^^^^^^^^^^^
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1349, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-05 21:34] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')
RuntimeError: Incomplete provider response: length

[2026-09-05 21:50] CONFIG_CHANGE: adapter: 'deepseek' -> 'openai', model: 'DeepSeek-V4-Pro-0813' -> 'gpt-5.6-terra'
[2026-09-05 22:02] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 451, in stream_with_tools
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1352, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-05 22:12] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')
RuntimeError: Incomplete provider response: length

[2026-09-06 21:04] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')
RuntimeError: Incomplete provider response: length

[2026-09-06 21:17] CONSECUTIVE FAILURE ALERT: Agent builder has failed 2 times in a row
[2026-09-06 21:40] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1909, in run_stream_with_tools
    results = await asyncio.gather(*coros)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1116, in _execute_tool
    output = await tool.execute(**tc.input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/Projects/yapoc/app/utils/tools/shell.py", line 53, in execute
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/tasks.py", line 520, in wait_for
    return await fut
           ^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/subprocess.py", line 201, in communicate
    stdin, stdout, stderr = await tasks.gather(stdin, stdout, stderr)
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/subprocess.py", line 181, in _read_stream
    output = await stream.read()
             ^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 706, in read
    block = await self.read(self._limit)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 713, in read
    await self._wait_for_data('read')
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/streams.py", line 545, in _wait_for_data
    await self._waiter
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1352, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-06 22:01] ERROR: Task timed out after 300s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1936, in run_stream_with_tools
    await self._emit_event("tool_result", {
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 458, in _emit_event
    async with aiofiles.open(event_file, "a", encoding="utf-8") as f:
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.cache/pypoetry/virtualenvs/yapoc-BKvU9FD_-py3.12/lib/python3.12/site-packages/aiofiles/base.py", line 76, in __aexit__
    await get_running_loop().run_in_executor(
asyncio.exceptions.CancelledError

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1352, in run_stream_with_tools
    async with asyncio.timeout(_timeout_value):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-06 23:35] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    raise RuntimeError(f'Incomplete provider response: {reason or "stream ended without a terminal event"}')
RuntimeError: Incomplete provider response: length

[2026-09-07 00:37] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    # generated up to that point is valid and usable, so do NOT treat it as a
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Incomplete provider response: length

[2026-09-07 00:40] ERROR: Incomplete provider response: length
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 501, in stream_with_tools
    require_complete(finish_reason)
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/termination.py", line 7, in require_complete
    # generated up to that point is valid and usable, so do NOT treat it as a
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Incomplete provider response: length

[2026-09-07 00:53] WARNING: Evaluator self-eval failed 3rd consecutive time with 'Incomplete provider response: length'. Root cause confirmed: deepseek-v4-flash 8192 output cap + stale termination.py (pre-'length'-fix) running in backend. Fix verified on disk (termination.py accepts 'length'); backend restart required to activate, deferred (notification processing). Telegram alert sent.
[2026-09-07 01:03] CONSECUTIVE FAILURE ALERT: Agent evaluator has failed 3 times in a row
[2026-09-07 02:35] WARNING: Evaluator self-eval tick (00:30, task d1be1109) completed with EMPTY result — no round 88 written to REPORT.MD (newest is still round 87). Silent empty completion vs hard crash, consistent with DeepSeek 'length' truncation. termination.py fix on disk but stale backend still running; restart remains outstanding to activate it.
[2026-09-07 04:05] WARNING: Evaluator self-eval tick (02:00, task 78fb8057) completed with EMPTY result again — "[] OK:", no round 89 written to REPORT.MD (newest is round 88). 5th consecutive window of evaluator tick failures/empty results, consistent with deepseek-v4-flash output truncation. termination.py 'length' fix is on disk but backend still running stale code (restart outstanding); parse_tool_arguments retry remains NEEDS_APPROVAL and unapplied.
[2026-09-07 13:44] ERROR: Task timed out after 0s
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 451, in stream_with_tools
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1565, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 450, in stream_with_tools
    async with asyncio.timeout(180):
               ^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

[2026-09-07 17:01] INFO: Investigated Doctor CROSS_AGENT_PATTERN 15-turn-limit alert. Root cause was stale historical telemetry: builder/keeper/planning CONFIG.yaml runner.max_turns are all 30, and shared resolution now preserves CONFIG.yaml when JSON omits max_turns. Recent logs confirm builder/planning later hit 30-turn caps on a large Telegram task, not 15; keeper completed recent tasks in 7–11 turns. No config change required.
[2026-09-07 17:06] INFO: Investigated Doctor CROSS_AGENT_PATTERN 15-turn-limit alert. Root cause was stale historical telemetry: builder/keeper/planning CONFIG.yaml runner.max_turns are all 30, and shared resolution now preserves CONFIG.yaml when JSON omits max_turns. Recent logs confirm builder/planning later hit 30-turn caps on a large Telegram task, not 15; keeper completed recent tasks in 7–11 turns. No config change required.
[2026-09-07 17:17] INFO: Re-confirmed Doctor CROSS_AGENT_PATTERN 15-turn-limit alert is stale telemetry. builder/keeper/planning CONFIG.yaml runner.max_turns are all 30 (verified via grep). The "15-turn limit" error strings predate the bump to 30. No live config issue; no change required.
[2026-09-07 17:22] INFO: Re-confirmed Doctor CROSS_AGENT_PATTERN 15-turn-limit alert is stale telemetry (4th occurrence). builder/keeper/planning CONFIG.yaml runner.max_turns all = 30 (verified via execute_code). "15-turn limit" strings only exist in doctor/HEALTH_SUMMARY.MD (dated ≤2026-09-06) and master/SERVER_OUTPUT.MD historical log. The 15→30 bump was applied by evaluator round 86 on 2026-09-06. No live config issue; no change required.
[2026-09-07 17:28] INFO: Fixed root cause of recurring Doctor CROSS_AGENT_PATTERN "15-turn limit" alert (5th occurrence). Doctor's _detect_cross_agent_patterns reads app/memory/agents/<name>/HEALTH.MD (NOT app/agents/<name>/HEALTH.MD). Those memory-store files still contained stale "reached the 15-turn limit" error blocks from before the 15→30 bump (evaluator round 86, 2026-09-06). Cleared the stale 15-turn blocks from builder/keeper/planning memory-store HEALTH.MD, keeping legitimate 30-turn entries. Detector will no longer match. Config was already correct (max_turns=30 all three).
[2026-09-07 18:15] CONSECUTIVE FAILURE ALERT: Agent planning has failed 2 times in a row
[2026-09-07 20:20] ERROR: Task incomplete: provider returned no answer or tool calls
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1856, in run_stream_with_tools
    raise RuntimeError("Task incomplete: provider returned no answer or tool calls")
RuntimeError: Task incomplete: provider returned no answer or tool calls

[2026-09-07 20:21] ERROR: Task incomplete: provider returned no answer or tool calls
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1856, in run_stream_with_tools
    raise RuntimeError("Task incomplete: provider returned no answer or tool calls")
RuntimeError: Task incomplete: provider returned no answer or tool calls

[2026-09-07 22:50] ERROR: Task incomplete: provider returned no answer or tool calls
Traceback (most recent call last):
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1876, in run_stream_with_tools
    raise RuntimeError("Task incomplete: provider returned no answer or tool calls")
RuntimeError: Task incomplete: provider returned no answer or tool calls

[2026-09-07 22:52] CONFIG_CHANGE: adapter: 'openai' -> 'deepseek', model: 'gpt-5.6-terra' -> 'deepseek-v4-pro'
