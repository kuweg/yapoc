"""Telegram bot integration for YAPOC — polling-based chat interface.

Uses raw httpx calls to the Telegram Bot API (no python-telegram-bot dependency).
Runs as an async background task in the FastAPI lifespan.

Architecture:
    - Long-polling via getUpdates with 30s timeout
    - Creates task_queue entries (source="telegram") for the dispatcher
    - Polls task_queue for completion and sends results back via sendMessage
    - Rate-limited to 1 message per second per chat
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.utils.db import create_queued_task, get_queued_task

# ── Constants ──────────────────────────────────────────────────────────────

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30  # seconds for long-polling getUpdates
POLL_INTERVAL = 1  # seconds between polls when no updates
TASK_POLL_INTERVAL = 1  # seconds between task_queue status checks
TASK_TIMEOUT = 300  # max seconds to wait for task completion
RATE_LIMIT_PER_CHAT = 1.0  # minimum seconds between messages to the same chat
MAX_RETRIES = 3  # max retries for Telegram API calls before giving up
RETRY_DELAY = 5  # seconds to wait before retrying after API error


class RateLimiter:
    """Simple per-chat rate limiter — enforces minimum interval between messages."""

    def __init__(self, default_interval: float = RATE_LIMIT_PER_CHAT) -> None:
        self._last_sent: dict[int, float] = {}
        self._default_interval = default_interval

    def can_send(self, chat_id: int) -> bool:
        """Check if we can send a message to this chat now."""
        last = self._last_sent.get(chat_id)
        if last is None:
            return True
        elapsed = (datetime.now(timezone.utc).timestamp() - last)
        return elapsed >= self._default_interval

    def record_send(self, chat_id: int) -> None:
        """Record that we just sent a message to this chat."""
        self._last_sent[chat_id] = datetime.now(timezone.utc).timestamp()

    async def wait_if_needed(self, chat_id: int) -> None:
        """Wait until we're allowed to send to this chat."""
        while not self.can_send(chat_id):
            await asyncio.sleep(0.1)


class TelegramBot:
    """Telegram bot using long-polling (getUpdates) via httpx.

    Usage:
        bot = TelegramBot(token="123:ABC")
        await bot.start()  # runs forever
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self._offset: int = 0  # getUpdates offset for acknowledging messages
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._rate_limiter = RateLimiter()
        self._running = False

    # ── Public API ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Main polling loop. Runs forever until cancelled."""
        self._running = True
        logger.info("Telegram bot: starting polling loop (token=...{})", self.token[-8:] if len(self.token) > 8 else "")

        while self._running:
            try:
                updates = await self._get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
                if updates is None:
                    # API error — wait and retry
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        self._offset = update_id + 1

                    message = update.get("message")
                    if message is not None:
                        await self._handle_message(message)

                # If no updates were returned, brief pause before next poll
                if not updates:
                    await asyncio.sleep(POLL_INTERVAL)

            except asyncio.CancelledError:
                logger.info("Telegram bot: polling loop cancelled")
                self._running = False
                break
            except Exception as exc:
                logger.warning("Telegram bot: polling loop error: {}", exc)
                await asyncio.sleep(RETRY_DELAY)

        await self._client.aclose()
        logger.info("Telegram bot: stopped")

    async def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._running = False

    # ── Telegram API calls ──────────────────────────────────────────────────

    async def _get_updates(self, offset: int, timeout: int) -> list[dict] | None:
        """Call getUpdates with long-polling timeout.

        Returns the list of updates, or None on error.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="getUpdates")
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return data.get("result", [])
                    else:
                        logger.warning(
                            "Telegram API error (getUpdates): {}",
                            data.get("description", "unknown"),
                        )
                        return None
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                    logger.warning(
                        "Telegram rate limited (getUpdates): retry after {}s",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning(
                        "Telegram API HTTP {} (getUpdates): {}",
                        response.status_code,
                        response.text[:200],
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
            except httpx.TimeoutException:
                # Timeout is expected with long-polling — return empty list
                return []
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable (getUpdates): {}", exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
        return None

    async def _send_message(self, chat_id: int, text: str) -> bool:
        """Send a text message to a Telegram chat.

        Returns True on success, False on failure.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        await self._rate_limiter.wait_if_needed(chat_id)

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        self._rate_limiter.record_send(chat_id)
                        return True
                    else:
                        logger.warning(
                            "Telegram API error (sendMessage): {}",
                            data.get("description", "unknown"),
                        )
                        return False
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                    logger.warning(
                        "Telegram rate limited (sendMessage): retry after {}s",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning(
                        "Telegram API HTTP {} (sendMessage): {}",
                        response.status_code,
                        response.text[:200],
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable (sendMessage): {}", exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
        return False

    # ── Message handling ────────────────────────────────────────────────────

    async def _handle_message(self, msg: dict) -> None:
        """Process a single incoming message.

        Handles:
        - /start and /help commands → welcome message
        - Private chat messages → forward to Master via task_queue
        - Group chat messages → only respond if bot is mentioned or starts with /
        """
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "")
        text = (msg.get("text") or "").strip()

        if not chat_id or not text:
            return

        # Determine if we should respond
        if chat_type == "private":
            # Always respond in private chats
            pass
        elif chat_type in ("group", "supergroup"):
            # Only respond if message starts with / or bot is mentioned
            if not text.startswith("/") and f"@{msg.get('from', {}).get('username', '')}" not in text:
                return
        else:
            # Unknown chat type — ignore
            return

        # Handle commands
        if text.startswith("/"):
            await self._handle_command(chat_id, text)
            return

        # Regular message — forward to Master via task_queue
        await self._handle_user_message(chat_id, text)

    async def _handle_command(self, chat_id: int, text: str) -> None:
        """Handle bot commands."""
        command = text.split()[0].lower()

        if command in ("/start", "/help"):
            welcome = (
                "🤖 <b>Welcome to YAPOC!</b>\n\n"
                "I'm connected to the YAPOC multi-agent system. "
                "Send me any message and I'll forward it to the Master agent for processing.\n\n"
                "<b>Commands:</b>\n"
                "/start — Show this welcome message\n"
                "/help — Show available commands\n\n"
                "<b>How it works:</b>\n"
                "1. You send a message\n"
                "2. It's queued for the Master agent\n"
                "3. Master processes it and sends the response back\n\n"
                "<i>Responses may take a few seconds depending on workload.</i>"
            )
            await self._send_message(chat_id, welcome)
        else:
            await self._send_message(
                chat_id,
                f"Unknown command: {command}\n\nSend /help to see available commands.",
            )

    async def _handle_user_message(self, chat_id: int, text: str) -> None:
        """Forward a user message to Master via task_queue and wait for result."""
        # Send immediate acknowledgment
        await self._send_message(chat_id, "⏳ Processing your request...")

        # Create task in queue
        task_id = str(uuid.uuid4())
        session_id = str(chat_id)

        try:
            create_queued_task(
                id=task_id,
                prompt=text,
                source="telegram",
                session_id=session_id,
            )
            logger.info(
                "Telegram bot: queued task {} from chat {} (text={!r:.80})",
                task_id[:8], chat_id, text,
            )
        except Exception as exc:
            logger.error("Telegram bot: failed to create task: {}", exc)
            await self._send_message(
                chat_id,
                "❌ Sorry, I couldn't create a task. Please try again later.",
            )
            return

        # Wait for result
        result = await self._wait_for_result(task_id, chat_id)
        if result is None:
            await self._send_message(
                chat_id,
                "❌ Sorry, the request timed out after 5 minutes. Please try again.",
            )
        else:
            # Truncate very long responses to avoid Telegram's 4096 char limit
            max_len = 4000
            if len(result) > max_len:
                result = result[:max_len] + "\n\n<i>... (response truncated)</i>"
            await self._send_message(chat_id, result)

    async def _wait_for_result(self, task_id: str, chat_id: int) -> str | None:
        """Poll task_queue for task completion.

        Polls every TASK_POLL_INTERVAL seconds, up to TASK_TIMEOUT seconds.
        Returns the result text on success, None on timeout.
        """
        start = datetime.now(timezone.utc).timestamp()
        while True:
            elapsed = datetime.now(timezone.utc).timestamp() - start
            if elapsed >= TASK_TIMEOUT:
                logger.warning(
                    "Telegram bot: task {} timed out after {}s",
                    task_id[:8], TASK_TIMEOUT,
                )
                return None

            try:
                task = get_queued_task(task_id)
            except Exception as exc:
                logger.error("Telegram bot: error polling task {}: {}", task_id[:8], exc)
                await asyncio.sleep(TASK_POLL_INTERVAL)
                continue

            if task is None:
                # Task not found — might still be pending creation
                await asyncio.sleep(TASK_POLL_INTERVAL)
                continue

            status = task.get("status", "")

            if status == "done":
                result = task.get("result", "")
                logger.info(
                    "Telegram bot: task {} completed ({} chars)",
                    task_id[:8], len(result),
                )
                return result

            if status == "error":
                error_msg = task.get("error", "Unknown error")
                logger.warning("Telegram bot: task {} failed: {}", task_id[:8], error_msg)
                return f"❌ An error occurred: {error_msg}"

            if status == "timeout":
                logger.warning("Telegram bot: task {} timed out in dispatcher", task_id[:8])
                return None

            # Still pending/running — keep polling
            await asyncio.sleep(TASK_POLL_INTERVAL)
