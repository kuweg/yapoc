"""FallbackAdapter — try a chain of providers until one works.

Wraps a list of ``AgentConfig`` entries (primary + ordered fallbacks) and
implements the :class:`BaseLLMAdapter` interface. For every call, the
adapter tries entry 0 first and falls through on errors that indicate
the provider is unreachable, unauthorized, rate-limited, or
mis-configured.

We only fall over to the next entry when the inner adapter fails **before
emitting anything usable**. Once we have started streaming events out to
the caller, we commit — restarting would double-bill the user and
produce garbled output. If a mid-stream error happens, it propagates to
the caller as usual.

Errors that trigger fallover:

- ``ValueError``  — typically raised by adapter constructors when the
  required API key is missing (``OpenAIAdapter``, ``GoogleAdapter``…).
- ``httpx.HTTPStatusError`` — any 4xx/5xx from an OpenAI-compat endpoint.
- ``httpx.ConnectError`` / ``httpx.ReadError`` / ``httpx.TimeoutException``
  — network failures.
- ``anthropic.APIError`` / ``APIConnectionError`` / ``RateLimitError`` /
  ``AuthenticationError``.
- ``asyncio.TimeoutError`` — upstream timeout.
- ``KeyError`` — malformed response JSON (defensive).

All failovers are logged to ``stderr`` via ``logging`` at WARNING level.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from .base import (
    AgentConfig,
    BaseLLMAdapter,
    Message,
    StreamEvent,
    ToolDefinition,
)

log = logging.getLogger(__name__)

try:
    import anthropic as _anthropic_sdk  # type: ignore
    _ANTHROPIC_ERRORS: tuple[type[BaseException], ...] = (
        _anthropic_sdk.APIError,
        _anthropic_sdk.APIConnectionError,
        _anthropic_sdk.RateLimitError,
        _anthropic_sdk.AuthenticationError,
    )
except Exception:  # pragma: no cover — anthropic is a hard dep, but be safe
    _ANTHROPIC_ERRORS = ()


# Exceptions that indicate "try the next fallback" rather than "fail hard".
_FALLOVER_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,  # missing API key at constructor time
    httpx.HTTPStatusError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.TimeoutException,
    asyncio.TimeoutError,
    KeyError,
    *_ANTHROPIC_ERRORS,
)


def _is_fallover(exc: BaseException) -> bool:
    return isinstance(exc, _FALLOVER_ERRORS)


class FallbackAdapter(BaseLLMAdapter):
    """Primary + ordered fallbacks that share the :class:`BaseLLMAdapter` interface.

    The primary config must be the first entry in ``chain``. The chain is
    **lazily** constructed — we only build an underlying adapter the first
    time we need it, which means a failing constructor (e.g. missing API
    key) still counts as a failover instead of crashing at config load.
    """

    def __init__(self, chain: list[AgentConfig]) -> None:
        if not chain:
            raise ValueError("FallbackAdapter requires at least one AgentConfig")
        # BaseLLMAdapter stores ``self._config`` — we advertise the primary.
        super().__init__(chain[0])
        self._chain = chain
        self._active_index = 0
        self._active_adapter: BaseLLMAdapter | None = None

    # ── Adapter resolution ──────────────────────────────────────────────

    def _build(self, index: int) -> BaseLLMAdapter:
        """Construct the inner adapter for chain position ``index``."""
        # Local import to avoid a cycle — fallback.py is imported from
        # adapters/__init__.py.
        from . import get_adapter
        return get_adapter(self._chain[index])

    def _describe(self, index: int) -> str:
        cfg = self._chain[index]
        return f"{cfg.adapter}:{cfg.model}"

    @property
    def active(self) -> BaseLLMAdapter:
        """Return (and lazily build) the currently-active inner adapter."""
        if self._active_adapter is None:
            self._active_adapter = self._build(self._active_index)
        return self._active_adapter

    def context_window_size(self) -> int:
        """Context window of whatever adapter is currently active."""
        try:
            return self.active.context_window_size()
        except _FALLOVER_ERRORS:
            # Active adapter can't even answer — assume primary's window.
            return self._chain[0].max_tokens * 16 if self._chain else 200_000

    # ── Internal fallover driver ────────────────────────────────────────

    async def _try_each(self, call):
        """Call ``call(adapter, cfg)`` for each chain entry until one succeeds.

        ``call`` must be an async callable accepting ``(adapter, cfg)``.
        Any exception matching ``_FALLOVER_ERRORS`` advances to the next
        entry. The first successful return value is returned. If every
        entry fails, the last exception is re-raised.
        """
        last_exc: BaseException | None = None
        for idx in range(len(self._chain)):
            try:
                adapter = self._build(idx)
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] construct %s failed (%s) — next",
                    self._describe(idx),
                    exc.__class__.__name__,
                )
                last_exc = exc
                continue
            try:
                result = await call(adapter, self._chain[idx])
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] %s failed (%s: %s) — trying next",
                    self._describe(idx),
                    exc.__class__.__name__,
                    str(exc)[:200],
                )
                last_exc = exc
                continue
            # Success — remember which one for context_window_size queries.
            self._active_index = idx
            self._active_adapter = adapter
            return result

        # Exhausted the chain.
        raise RuntimeError(
            f"All {len(self._chain)} adapters in the fallback chain failed. "
            f"Last error: {last_exc!r}"
        ) from last_exc

    # ── Non-streaming ───────────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> str:
        async def _call(adapter: BaseLLMAdapter, cfg: AgentConfig) -> str:
            return await adapter.complete(system_prompt, user_message, history)
        return await self._try_each(_call)

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        history: list[Message] | None = None,
    ) -> AsyncIterator[str]:
        """Stream plain text from whichever adapter comes up first.

        We can't retry once text has started flowing to the caller, so we
        buffer the first chunk from each adapter. If the first chunk
        raises, we move on; once we have it, we commit and stream the
        rest directly.
        """
        last_exc: BaseException | None = None
        for idx in range(len(self._chain)):
            try:
                adapter = self._build(idx)
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] construct %s failed (%s) — next",
                    self._describe(idx),
                    exc.__class__.__name__,
                )
                last_exc = exc
                continue

            gen = adapter.stream(system_prompt, user_message, history)
            first_chunk: str | None = None
            try:
                async for chunk in gen:
                    first_chunk = chunk
                    break
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] %s stream init failed (%s) — trying next",
                    self._describe(idx),
                    exc.__class__.__name__,
                )
                last_exc = exc
                continue

            # Committed — this adapter gave us something, use it for the rest.
            self._active_index = idx
            self._active_adapter = adapter
            if first_chunk is not None:
                yield first_chunk
            try:
                async for chunk in gen:
                    yield chunk
            except Exception:
                # Mid-stream failure — propagate. Can't recover cleanly.
                raise
            return

        raise RuntimeError(
            f"All {len(self._chain)} adapters in the fallback chain failed "
            f"to start streaming. Last error: {last_exc!r}"
        ) from last_exc

    # ── Streaming with tools ────────────────────────────────────────────

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """Streaming tool-use with fallover on early failure.

        Same committed-once-we-emit semantics as ``stream()``. For long
        conversations with tool calls this is the hot path and the one
        that needs to be resilient to 429/5xx blips.
        """
        last_exc: BaseException | None = None
        for idx in range(len(self._chain)):
            try:
                adapter = self._build(idx)
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] construct %s failed (%s) — next",
                    self._describe(idx),
                    exc.__class__.__name__,
                )
                last_exc = exc
                continue

            gen = adapter.stream_with_tools(system_prompt, messages, tools)
            first_event: StreamEvent | None = None
            try:
                async for event in gen:
                    first_event = event
                    break
            except _FALLOVER_ERRORS as exc:
                log.warning(
                    "[fallback] %s stream_with_tools init failed (%s: %s) — next",
                    self._describe(idx),
                    exc.__class__.__name__,
                    str(exc)[:200],
                )
                last_exc = exc
                continue

            # Committed.
            self._active_index = idx
            self._active_adapter = adapter
            if idx > 0:
                log.warning(
                    "[fallback] using fallback #%d (%s) after primary failure",
                    idx,
                    self._describe(idx),
                )
            if first_event is not None:
                yield first_event
            try:
                async for event in gen:
                    yield event
            except Exception:
                # Mid-stream failure — propagate. Cannot resume cleanly
                # because tool calls may have already been emitted.
                raise
            return

        raise RuntimeError(
            f"All {len(self._chain)} adapters in the fallback chain failed "
            f"to start streaming tools. Last error: {last_exc!r}"
        ) from last_exc
