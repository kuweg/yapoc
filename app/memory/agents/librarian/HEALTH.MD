[2026-09-02 13:55] ERROR: Task timed out after 900s
Traceback (most recent call last):
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
  File "/home/kuweg/Projects/yapoc/app/agents/base/__init__.py", line 1537, in run_stream_with_tools
    async for event in adapter.stream_with_tools(
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/fallback.py", line 309, in stream_with_tools
    async for event in gen:
  File "/home/kuweg/Projects/yapoc/app/utils/adapters/deepseek.py", line 447, in stream_with_tools
    async with asyncio.timeout(180):
               ^^^^^^^^^^^^^^^^^^^^
  File "/home/kuweg/.local/share/mise/installs/python/3.12.14/lib/python3.12/asyncio/timeouts.py", line 115, in __aexit__
    raise TimeoutError from exc_val
TimeoutError

