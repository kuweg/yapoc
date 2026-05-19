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

import html as _html

import httpx
from loguru import logger

from app.config import settings
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


def _escape_html(text: str) -> str:
    """Escape text for safe use with Telegram's HTML parse_mode.

    Telegram's HTML parser accepts: <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">
    Everything else must be escaped to avoid parse errors.
    """
    return _html.escape(text, quote=False)


class Authenticator:
    """Simple PIN-based authentication for Telegram users.

    Users must send /auth <PIN> before the bot accepts their messages.
    Once authenticated, their chat_id is cached in memory for the session.
    Bot restarts = re-auth required.
    """

    def __init__(self, pin: str, whitelist: list[int] | None = None) -> None:
        self._pin = pin
        self._whitelist: set[int] = set(whitelist or [])
        self._authorized_chats: set[int] = set()

    def is_authorized(self, chat_id: int) -> bool:
        """Check if a chat is already authenticated (whitelisted or previously authed)."""
        return chat_id in self._authorized_chats or chat_id in self._whitelist

    def authenticate(self, chat_id: int, provided_pin: str) -> bool:
        """Attempt to authenticate a chat. Returns True on success."""
        if provided_pin == self._pin:
            self._authorized_chats.add(chat_id)
            return True
        return False

    @property
    def enabled(self) -> bool:
        return bool(self._pin) or bool(self._whitelist)


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

    Thread-safety / restart safety:
        Uses a class-level lock and active-instance tracker to prevent
        multiple instances from polling the same token simultaneously.
        When a new instance starts (e.g. after server restart), it signals
        the old instance to stop before beginning its own polling loop.
        This prevents duplicate message responses during server restarts.
    """

    # Class-level coordination to prevent duplicate polling across restarts
    _instance_lock = asyncio.Lock()
    _active_instance: "TelegramBot | None" = None
    _processed_update_ids_global: set[int] = set()  # shared across instances to survive restart overlap
    _recent_message_ids: set[tuple[int, int]] = set()  # shared (chat_id, message_id) dedup across instances

    def __init__(self, token: str) -> None:
        self.token = token
        self._offset: int = 0  # getUpdates offset for acknowledging messages
        self._processed_update_ids: set[int] = TelegramBot._processed_update_ids_global  # shared dedup across polls
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._rate_limiter = RateLimiter()
        self._auth = Authenticator(settings.telegram_auth_pin, settings.telegram_whitelist)
        self._bot_username: str | None = None  # lazily fetched via getMe
        self._running = False
        self._shutdown_event = asyncio.Event()  # signals polling loop to exit promptly

    # ── Public API ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Main polling loop. Runs forever until cancelled.

        Uses a class-level lock to prevent multiple instances from polling
        the same token simultaneously. If another instance is already running,
        signals it to stop before starting.
        """
        async with TelegramBot._instance_lock:
            # Signal any existing active instance to stop
            old_instance = TelegramBot._active_instance
            if old_instance is not None and old_instance is not self:
                logger.info("Telegram bot: signaling previous instance to stop")
                await old_instance.stop()
                # Wait for the old instance's polling loop to fully exit.
                # stop() force-closes the HTTP client, which should cause
                # _get_updates to raise RequestError immediately. But the
                # polling loop's except handler and while-condition check
                # still need time to run. Without this wait, the new instance
                # can start polling before the old one has fully stopped,
                # causing both instances to receive the same updates.
                for _ in range(50):  # wait up to 5s
                    if not old_instance._running:
                        break
                    await asyncio.sleep(0.1)
                if old_instance._running:
                    logger.warning(
                        "Telegram bot: previous instance still running after 5s — "
                        "proceeding anyway (risk of duplicate updates)"
                    )

            TelegramBot._active_instance = self
            self._running = True
            self._shutdown_event.clear()

        logger.info("Telegram bot: starting polling loop (token=...{})", self.token[-8:] if len(self.token) > 8 else "")

        while self._running and not self._shutdown_event.is_set():
            try:
                updates = await self._get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
                if updates is None:
                    # API error — wait and retry
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        # Deduplicate: Telegram's API guarantees at-least-once
                        # delivery and may return the same update_id twice
                        # within a single poll or across polls. Skip any
                        # update_id we've already processed.
                        if update_id in self._processed_update_ids:
                            continue
                        self._processed_update_ids.add(update_id)
                        self._offset = update_id + 1

                    message = update.get("message")
                    if message is not None:
                        await self._handle_message(message)

                # Prune processed IDs periodically to prevent unbounded memory
                # growth. Keep only the last 1000 IDs — far more than any
                # realistic duplicate window.
                if len(self._processed_update_ids) > 1000:
                    self._processed_update_ids = set(sorted(self._processed_update_ids)[-500:])

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
        """Signal the polling loop to stop and wait for it to exit.

        Forcefully closes the HTTP client to abort any in-flight getUpdates
        long-poll (30s timeout), then waits for the polling loop to notice
        the shutdown signal and exit. This prevents the old instance from
        still polling after the new instance starts — the root cause of
        duplicate message processing during server restarts.
        """
        self._running = False
        self._shutdown_event.set()
        # Force-close the HTTP client to abort any in-flight getUpdates
        # long-poll immediately, instead of waiting for the 30s timeout.
        # This is the critical fix: without it, the old instance can still
        # receive and process updates for up to 30s after the new instance
        # starts, causing duplicate responses.
        await self._client.aclose()
        # Give the polling loop time to notice the shutdown signal
        # (it will get a httpx.RequestError from the closed client)
        for _ in range(50):  # wait up to 5 seconds (client close aborts the poll instantly)
            if not self._running:
                break
            await asyncio.sleep(0.1)

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
                # If we're shutting down (client was closed by stop()), exit
                # immediately instead of retrying. This prevents the old
                # instance from blocking for up to 15s of retries while the
                # new instance is already polling.
                if not self._running or self._shutdown_event.is_set():
                    logger.info("Telegram bot: getUpdates aborted (shutting down)")
                    return None
                logger.warning("Telegram API unreachable (getUpdates): {}", exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
        return None

    async def _send_message(self, chat_id: int, text: str) -> int | None:
        """Send a text message to a Telegram chat.

        Returns the message_id on success, None on failure.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": chat_id,
            "text": _escape_html(text),
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
                        result = data.get("result", {})
                        return result.get("message_id")
                    else:
                        desc = data.get("description", "unknown")
                        # "message is not modified" can also happen on sendMessage
                        # if Telegram deduplicates — treat as success
                        if "message is not modified" in desc.lower():
                            return None  # no new message_id, but not an error
                        logger.warning(
                            "Telegram API error (sendMessage): {}",
                            desc,
                        )
                        return None
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
        return None

    async def _edit_message(self, chat_id: int, message_id: int, text: str, parse_mode: str | None = "HTML") -> bool:
        """Edit a previously sent message.

        Args:
            chat_id: Target chat ID.
            message_id: ID of the message to edit.
            text: New text content.
            parse_mode: Parse mode ("HTML", "MarkdownV2", or None for plain text).

        Returns True on success, False on failure.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="editMessageText")
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": _escape_html(text) if parse_mode else text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return True
                    else:
                        desc = data.get("description", "unknown")
                        # "message is not modified" means the edit succeeded
                        # but the content was identical — treat as success
                        if "message is not modified" in desc.lower():
                            return True
                        logger.warning(
                            "Telegram API error (editMessageText): {}",
                            desc,
                        )
                        return False
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                    logger.warning(
                        "Telegram rate limited (editMessageText): retry after {}s",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning(
                        "Telegram API HTTP {} (editMessageText): {}",
                        response.status_code,
                        response.text[:200],
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable (editMessageText): {}", exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
        return False

    # ── Message handling ────────────────────────────────────────────────────

    async def _get_bot_username(self) -> str:
        """Fetch the bot's own username via the getMe API, caching it."""
        if self._bot_username is None:
            try:
                resp = await self._client.get(
                    f"https://api.telegram.org/bot{self.token}/getMe",
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    self._bot_username = data["result"].get("username", "")
            except Exception:
                pass
        return self._bot_username or ""

    async def _is_bot_mentioned(self, text: str) -> bool:
        """Check if the bot is mentioned in the text (e.g. @MyBot)."""
        username = await self._get_bot_username()
        if not username:
            return False
        return f"@{username}" in text

    def _extract_forward_info(self, msg: dict) -> str:
        """Extract forward metadata from a Telegram message dict.

        Returns a human-readable prefix string describing the forward origin,
        or an empty string if the message is not forwarded.

        Handles both the new forward_origin API and legacy forward_* fields.
        """
        # New API: forward_origin object
        forward_origin = msg.get("forward_origin")
        if forward_origin is not None and isinstance(forward_origin, dict):
            origin_type = forward_origin.get("type", "")
            if origin_type == "user":
                sender = forward_origin.get("sender_user", {})
                if isinstance(sender, dict):
                    first = sender.get("first_name", "")
                    last = sender.get("last_name", "")
                    username = sender.get("username", "")
                    name = f"{first} {last}".strip()
                    if username:
                        return f"📨 *Forwarded from user* @{username} ({name}):\n\n"
                    elif name:
                        return f"📨 *Forwarded from user* {name}:\n\n"
                    else:
                        return "📨 *Forwarded from user*:\n\n"
            elif origin_type == "chat":
                sender_chat = forward_origin.get("sender_chat", {})
                if isinstance(sender_chat, dict):
                    title = sender_chat.get("title", "")
                    chat_type = sender_chat.get("type", "group")
                    label = "group" if chat_type in ("group", "supergroup") else chat_type
                    if title:
                        return f"📨 *Forwarded from {label}* {title}:\n\n"
                    else:
                        return f"📨 *Forwarded from {label}*:\n\n"
            elif origin_type == "channel":
                chat = forward_origin.get("chat", {})
                if isinstance(chat, dict):
                    title = chat.get("title", "")
                    if title:
                        return f"📨 *Forwarded from channel* {title}:\n\n"
                    else:
                        return "📨 *Forwarded from channel*:\n\n"
            elif origin_type == "hidden_user":
                sender_name = forward_origin.get("sender_user_name", "")
                if sender_name:
                    return f"📨 *Forwarded from hidden user* ({sender_name}):\n\n"
                else:
                    return "📨 *Forwarded from hidden user*:\n\n"

        # Legacy API: forward_from, forward_from_chat, forward_sender_name
        forward_from = msg.get("forward_from")
        if forward_from is not None and isinstance(forward_from, dict):
            first = forward_from.get("first_name", "")
            last = forward_from.get("last_name", "")
            username = forward_from.get("username", "")
            name = f"{first} {last}".strip()
            if username:
                return f"📨 *Forwarded from user* @{username} ({name}):\n\n"
            elif name:
                return f"📨 *Forwarded from user* {name}:\n\n"
            else:
                return "📨 *Forwarded from user*:\n\n"

        forward_from_chat = msg.get("forward_from_chat")
        if forward_from_chat is not None and isinstance(forward_from_chat, dict):
            title = forward_from_chat.get("title", "")
            chat_type = forward_from_chat.get("type", "group")
            label = "group" if chat_type in ("group", "supergroup") else chat_type
            if title:
                return f"📨 *Forwarded from {label}* {title}:\n\n"
            else:
                return f"📨 *Forwarded from {label}*:\n\n"

        forward_sender_name = msg.get("forward_sender_name")
        if forward_sender_name:
            return f"📨 *Forwarded from hidden user* ({forward_sender_name}):\n\n"

        return ""

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

        # Message-level dedup: Telegram guarantees at-least-once delivery.
        # Even with update_id dedup, a restart can cause the same message
        # to arrive under a different update_id. Use (chat_id, message_id)
        # as a second dedup layer shared across all instances.
        message_id = msg.get("message_id")
        if chat_id is not None and message_id is not None:
            dedup_key = (chat_id, message_id)
            if dedup_key in TelegramBot._recent_message_ids:
                logger.warning(
                    "Telegram bot: duplicate message (chat={}, msg={}) — skipping",
                    chat_id, message_id,
                )
                return
            TelegramBot._recent_message_ids.add(dedup_key)
            # Prune old entries periodically (keep last 5000)
            if len(TelegramBot._recent_message_ids) > 5000:
                TelegramBot._recent_message_ids = set(
                    sorted(TelegramBot._recent_message_ids)[-2500:]
                )

        # Check for forwarded message and prepend metadata
        forward_prefix = self._extract_forward_info(msg)
        if forward_prefix:
            if text:
                text = forward_prefix + text
            else:
                # Forwarded media without caption
                text = forward_prefix + "📎 *Forwarded media*"

        if not chat_id or not text:
            return

        # Authentication check
        if self._auth.enabled and not self._auth.is_authorized(chat_id):
            # Only allow /auth command
            if text.startswith("/auth"):
                await self._handle_auth(chat_id, text)
            else:
                await self._send_message(
                    chat_id,
                    "🔒 <b>Authentication required.</b>\n\n"
                    "Send <code>/auth &lt;PIN&gt;</code> to authenticate.\n\n"
                    "Don't have the PIN? Contact the bot owner.",
                )
            return

        # Determine if we should respond
        if chat_type == "private":
            # Always respond in private chats
            pass
        elif chat_type in ("group", "supergroup"):
            # Only respond if message starts with / or bot is mentioned.
            # The bot's username is extracted from the token (before the colon
            # is the bot ID, not the username). We fetch it lazily via getMe.
            if not text.startswith("/") and not await self._is_bot_mentioned(text):
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
                "/help — Show available commands\n"
                "/auth &lt;PIN&gt; — Authenticate with the bot\n\n"
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

    async def _handle_auth(self, chat_id: int, text: str) -> None:
        """Handle /auth command — authenticate a user."""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send_message(
                chat_id,
                "🔒 Usage: <code>/auth &lt;PIN&gt;</code>\n\n"
                "Example: <code>/auth 1234</code>",
            )
            return

        provided_pin = parts[1].strip()
        if self._auth.authenticate(chat_id, provided_pin):
            await self._send_message(
                chat_id,
                "✅ <b>Authentication successful!</b>\n\n"
                "You can now send messages to the bot.\n\n"
                "Send /help to see available commands.",
            )
            logger.info("Telegram bot: chat {} authenticated successfully", chat_id)
        else:
            await self._send_message(
                chat_id,
                "❌ <b>Invalid PIN.</b> Please try again.\n\n"
                "Usage: <code>/auth &lt;PIN&gt;</code>",
            )
            logger.warning("Telegram bot: failed auth attempt from chat {}", chat_id)

    async def _handle_user_message(self, chat_id: int, text: str) -> None:
        """Forward a user message to Master via task_queue and wait for result."""
        # Dedup: use (chat_id, text) as a simple dedup key within a short window
        # to prevent the same message from being processed twice.
        dedup_key = (chat_id, text)
        now = datetime.now(timezone.utc).timestamp()
        if not hasattr(self, '_recent_messages'):
            self._recent_messages: dict[tuple, float] = {}
        if dedup_key in self._recent_messages:
            elapsed = now - self._recent_messages[dedup_key]
            if elapsed < 5.0:  # 5-second dedup window
                logger.warning(
                    "Telegram bot: duplicate message from chat {} (text={!r:.40}), skipping",
                    chat_id, text,
                )
                return
        self._recent_messages[dedup_key] = now
        # Prune old entries
        self._recent_messages = {k: v for k, v in self._recent_messages.items() if now - v < 30}
        # Send immediate acknowledgment and capture message_id.
        # Retry up to 3 times to ensure we get a message_id for later editing.
        ack_msg_id = None
        for _attempt in range(3):
            ack_msg_id = await self._send_message(chat_id, "⏳ Processing your request...")
            if ack_msg_id is not None:
                break
            await asyncio.sleep(1)
        if ack_msg_id is None:
            logger.warning(
                "Telegram bot: failed to send acknowledgment to chat {} after 3 attempts",
                chat_id,
            )
            # Continue anyway — we'll try to send the result later

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
            error_text = "❌ Sorry, the request timed out after 5 minutes. Please try again."
            if ack_msg_id is not None:
                edited = await self._edit_message(chat_id, ack_msg_id, error_text)
                if edited:
                    return
                # HTML edit failed — try plain text
                edited = await self._edit_message(chat_id, ack_msg_id, error_text, parse_mode=None)
                if edited:
                    return
                # Both edits failed — send new message
                await self._send_message(chat_id, error_text)
            else:
                await self._send_message(chat_id, error_text)
        else:
            # Truncate very long responses to avoid Telegram's 4096 char limit
            max_len = 4000
            if len(result) > max_len:
                result = result[:max_len] + "\n\n<i>... (response truncated)</i>"

            # Try to edit the acknowledgment message with the result
            if ack_msg_id is not None:
                edited = await self._edit_message(chat_id, ack_msg_id, result)
                if edited:
                    return  # Success — only one message visible

                # HTML edit failed (likely HTML-unsafe characters) — try plain text
                edited = await self._edit_message(chat_id, ack_msg_id, result, parse_mode=None)
                if edited:
                    return  # Success with plain text

            # Fall back to sending a new message
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


# ── Global instance accessor ──────────────────────────────────────────────

_telegram_bot_instance: "TelegramBot | None" = None


def set_telegram_bot_instance(bot: "TelegramBot") -> None:
    """Set the global TelegramBot instance for tool access."""
    global _telegram_bot_instance
    _telegram_bot_instance = bot


def get_telegram_bot_instance() -> "TelegramBot | None":
    """Get the global TelegramBot instance, or None if not set."""
    return _telegram_bot_instance
