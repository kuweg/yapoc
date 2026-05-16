"""Redis message bus — inter-agent communication backbone.

Streams (guaranteed delivery with consumer groups, ACK):
    agent:{name}:inbox          — messages sent TO this agent

Pub/Sub (fire-and-forget, no persistence):
    session:{id}:events         — streaming deltas (thinking, text, tool_call, tool_result)
    agent:{name}:status         — state changes (idle, running, error, terminated)
    system:health               — doctor → master alerts
    system:tasks                — global task lifecycle (created, assigned, completed, error)

Local outbox buffer (.outbox.jsonl) catches messages when Redis is unreachable.
On reconnect, the outbox is drained FIFO.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

import redis.asyncio as redis
from loguru import logger

from app.config import settings


class RedisBus:
    """Manages Redis connection, streams, pub/sub, and outbox buffering."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._redis: redis.Redis | None = None
        self._lock = asyncio.Lock()
        self._connected = False

    # ── Connection lifecycle ──────────────────────────────────────────

    async def connect(self) -> bool:
        """Connect to Redis. Returns True on success, False otherwise."""
        async with self._lock:
            if self._connected and self._redis:
                return True
            try:
                self._redis = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )
                await self._redis.ping()
                self._connected = True
                logger.info("RedisBus connected to {}", self._redis_url)
                return True
            except Exception as exc:
                logger.warning("RedisBus connect failed ({}): {}", self._redis_url, exc)
                self._connected = False
                self._redis = None
                return False

    async def disconnect(self) -> None:
        """Close Redis connection."""
        async with self._lock:
            if self._redis:
                try:
                    await self._redis.aclose()
                except Exception:
                    pass
                self._redis = None
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._redis is not None

    async def _ensure_connected(self) -> bool:
        if self.connected:
            return True
        return await self.connect()

    # ── Stream operations ─────────────────────────────────────────────

    async def stream_add(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int = 10000,
        agent_name: str | None = None,
    ) -> str | None:
        """XADD a message to a stream. Falls back to outbox if Redis is down."""
        if not await self._ensure_connected():
            if agent_name:
                await self.outbox_append(agent_name, stream, data, is_stream=True)
            return None
        try:
            msg_id = await self._redis.xadd(stream, {"json": json.dumps(data)}, maxlen=max_len)
            return msg_id
        except Exception as exc:
            logger.warning("RedisBus stream_add({}) failed: {}", stream, exc)
            if agent_name:
                await self.outbox_append(agent_name, stream, data, is_stream=True)
            return None

    async def stream_create_group(
        self, stream: str, group: str, start_id: str = "0"
    ) -> bool:
        """XGROUP CREATE for a stream. Idempotent (BUSYGROUP is not an error)."""
        if not await self._ensure_connected():
            return False
        try:
            await self._redis.xgroup_create(stream, group, id=start_id, mkstream=True)
            logger.debug("RedisBus created consumer group {} on {}", group, stream)
            return True
        except redis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return True
            logger.warning(
                "RedisBus xgroup_create({}, {}) failed: {}", stream, group, exc
            )
            return False
        except Exception as exc:
            logger.warning(
                "RedisBus xgroup_create({}, {}) failed: {}", stream, group, exc
            )
            return False

    async def stream_read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int = 5000,
        count: int = 1,
    ) -> list[dict[str, Any]]:
        """XREADGROUP — blocking read from a stream as part of a consumer group.

        Returns list of dicts: {"id": msg_id, "stream": stream, "data": parsed_json}
        """
        if not await self._ensure_connected():
            return []
        try:
            result = await self._redis.xreadgroup(
                group,
                consumer,
                {stream: ">"},
                block=block_ms,
                count=count,
            )
            if not result:
                return []
            messages: list[dict[str, Any]] = []
            for _stream_name, entries in result:
                for msg_id, fields in entries:
                    try:
                        data = json.loads(fields.get("json", "{}"))
                    except json.JSONDecodeError:
                        data = dict(fields)
                    messages.append({"id": msg_id, "stream": stream, "data": data})
            return messages
        except Exception as exc:
            logger.warning(
                "RedisBus stream_read_group({}, {}) failed: {}", stream, group, exc
            )
            return []

    async def stream_ack(self, stream: str, group: str, *msg_ids: str) -> int:
        """XACK one or more messages."""
        if not await self._ensure_connected() or not msg_ids:
            return 0
        try:
            return await self._redis.xack(stream, group, *msg_ids)
        except Exception as exc:
            logger.warning("RedisBus stream_ack({}) failed: {}", stream, exc)
            return 0

    async def stream_claim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 30000,
    ) -> list[dict[str, Any]]:
        """XAUTOCLAIM — claim messages pending longer than min_idle_ms."""
        if not await self._ensure_connected():
            return []
        try:
            result = await self._redis.xautoclaim(
                stream,
                group,
                consumer,
                min_idle_time=min_idle_ms,
                count=10,
            )
            messages: list[dict[str, Any]] = []
            for msg_id, fields in result[1]:
                try:
                    data = json.loads(fields.get("json", "{}"))
                except json.JSONDecodeError:
                    data = dict(fields)
                messages.append({"id": msg_id, "stream": stream, "data": data})
            return messages
        except Exception as exc:
            logger.warning(
                "RedisBus stream_claim_pending({}) failed: {}", stream, exc
            )
            return []

    # ── Pub/Sub ───────────────────────────────────────────────────────

    async def publish(
        self,
        channel: str,
        data: dict[str, Any],
        agent_name: str | None = None,
    ) -> int:
        """PUBLISH to a channel. Falls back to outbox if Redis is down.

        Returns number of subscribers that received the message (0 on failure).
        """
        if not await self._ensure_connected():
            if agent_name:
                await self.outbox_append(agent_name, channel, data, is_stream=False)
            return 0
        try:
            return await self._redis.publish(channel, json.dumps(data))
        except Exception as exc:
            logger.warning("RedisBus publish({}) failed: {}", channel, exc)
            if agent_name:
                await self.outbox_append(agent_name, channel, data, is_stream=False)
            return 0

    async def subscribe(self, *channels: str) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to one or more channels. Async iterator yielding decoded messages.

        Yields dicts: {"channel": str, "data": parsed_json}
        """
        if not await self._ensure_connected():
            return
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(*channels)
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        decoded = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        decoded = msg["data"]
                    yield {"channel": msg["channel"], "data": decoded}
        finally:
            try:
                await pubsub.unsubscribe(*channels)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass

    async def psubscribe(self, *patterns: str) -> AsyncIterator[dict[str, Any]]:
        """Pattern-subscribe to channel patterns. Async iterator.

        Yields dicts: {"channel": str, "pattern": str, "data": parsed_json}
        """
        if not await self._ensure_connected():
            return
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(*patterns)
            async for msg in pubsub.listen():
                if msg["type"] == "pmessage":
                    try:
                        decoded = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        decoded = msg["data"]
                    yield {
                        "channel": msg["channel"],
                        "pattern": msg["pattern"],
                        "data": decoded,
                    }
        finally:
            try:
                await pubsub.punsubscribe(*patterns)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass

    # ── Outbox buffer ─────────────────────────────────────────────────

    def _outbox_path(self, agent_name: str) -> Path:
        return settings.agents_dir / agent_name / ".outbox.jsonl"

    async def outbox_append(
        self,
        agent_name: str,
        target: str,
        data: dict[str, Any],
        is_stream: bool = True,
    ) -> None:
        """Buffer a message to the agent's local outbox file."""
        path = self._outbox_path(agent_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"target": target, "is_stream": is_stream, "data": data}
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:
            logger.warning(
                "RedisBus outbox_append({}) failed: {}", agent_name, exc
            )

    async def flush_outbox(self, agent_name: str) -> int:
        """Drain the agent's outbox to Redis. Returns count of flushed messages."""
        path = self._outbox_path(agent_name)
        if not path.exists():
            return 0

        if not await self._ensure_connected():
            return 0

        flushed = 0
        remaining: list[str] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        target = entry["target"]
                        is_stream = entry.get("is_stream", True)
                        data = entry["data"]
                        if is_stream:
                            result = await self.stream_add(target, data)
                        else:
                            result = await self.publish(target, data)
                        if result:
                            flushed += 1
                        else:
                            remaining.append(line)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as exc:
            logger.warning(
                "RedisBus flush_outbox({}) read failed: {}", agent_name, exc
            )
            return 0

        if remaining:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for line in remaining:
                        f.write(line + "\n")
            except OSError:
                pass
        else:
            try:
                path.unlink()
            except OSError:
                pass

        if flushed:
            logger.info(
                "RedisBus flushed {} outbox messages for {}",
                flushed,
                agent_name,
            )
        return flushed


# Module-level singleton — wired into lifespan in app/backend/main.py
bus = RedisBus()
