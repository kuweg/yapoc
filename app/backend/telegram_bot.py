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
import json
import time as _time
import uuid
from datetime import datetime, timezone

import html as _html
import re
from typing import Any

import httpx
from loguru import logger

from app.config import settings
from app.utils.db import create_queued_task, get_queued_task, clear_session_tasks

# ── Constants ──────────────────────────────────────────────────────────────

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30  # seconds for long-polling getUpdates
POLL_INTERVAL = 1  # seconds between polls when no updates
TASK_POLL_INTERVAL = 1  # seconds between task_queue status checks
TASK_TIMEOUT = 300  # max seconds to wait for task completion
RATE_LIMIT_PER_CHAT = 1.0  # minimum seconds between messages to the same chat
MAX_RETRIES = 3  # max retries for Telegram API calls before giving up
RETRY_DELAY = 5  # seconds to wait before retrying after API error

# Models confirmed to support vision/image input
VISION_CAPABLE_MODELS: frozenset[str] = frozenset({
    # Anthropic Claude (all modern versions support vision)
    "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307",
    "claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20240620", "claude-3-5-haiku-20241022",
    "claude-3-7-sonnet-20250219", "claude-sonnet-4-5", "claude-sonnet-4-6",
    "claude-opus-4-5", "claude-haiku-4-5", "claude-haiku-4-5-20251001",
    # OpenAI GPT-4 vision-capable
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision-preview",
    "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5", "gpt-5.1", "gpt-5.2",
    "gpt-5.4-mini", "gpt-5.4-nano",
    # Google Gemini (all multimodal)
    "gemini-pro-vision", "gemini-1.5-pro", "gemini-1.5-flash",
    "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite",
})

# Allowed Telegram HTML tags — these are preserved; everything else is escaped.
_TELEGRAM_HTML_TAG_RE = re.compile(
    r"<(?P<tag>/?(?:b|i|u|s|code|pre)(?:\s+[^>]*)?)>|"
    r"<(?P<ahref>a\s+href=[\"'][^\"']*[\"'])(?:\s+[^>]*)?>(?P<atext>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)


def _markdown_to_telegram_html(text: str) -> str:
    """Convert common Markdown formatting to Telegram HTML.

    Handles: **bold**, *italic*, _italic_, ~~strikethrough~~, `inline code`,
    [links](url), and ```code blocks```.

    Code blocks and inline code are protected with placeholders so markdown
    transformations don't corrupt literal content inside them.
    """
    placeholders: dict[str, str] = {}
    counter = 0

    def _placeholder(content: str) -> str:
        nonlocal counter
        key = f"\x00PH_{counter}\x00"
        counter += 1
        placeholders[key] = content
        return key

    # Code blocks (```...```) -> <pre>...</pre>
    def _code_block_repl(m: re.Match) -> str:
        code = m.group(1) or ""
        code = code.strip("\n")
        return _placeholder(f"<pre>{code}</pre>")

    text = re.sub(r"```(?:\w+)?\n?(.*?)```", _code_block_repl, text, flags=re.DOTALL)

    # Inline code (`text`) -> <code>text</code>
    def _inline_code_repl(m: re.Match) -> str:
        code = m.group(1) or ""
        return _placeholder(f"<code>{code}</code>")

    text = re.sub(r"(?<!\w)`([^`]+)`(?!\w)", _inline_code_repl, text)

    # Strikethrough (~~text~~) -> <s>text</s>
    text = re.sub(r"(?<!\w)~~(.+?)~~(?!\w)", r"<s>\1</s>", text)
    # Bold (**text**) -> <b>text</b>
    text = re.sub(r"(?<!\w)\*\*(.+?)\*\*(?!\w)", r"<b>\1</b>", text)
    # Italic (*text* or _text_) -> <i>text</i>
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)
    # Links ([text](url)) -> <a href="url">text</a>
    text = re.sub(r"(?<!\w)\[([^\]]+)\]\(([^)]+)\)(?!\w)", r'<a href="\2">\1</a>', text)

    # Restore placeholders
    for key, val in placeholders.items():
        text = text.replace(key, val)

    return text


def _escape_html(text: str) -> str:
    """Escape text for safe use with Telegram's HTML parse_mode.

    Telegram's HTML parser accepts: <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">
    Everything else (raw <, >, &) is escaped to avoid parse errors.
    """
    parts: list[str] = []
    last_end = 0

    for m in _TELEGRAM_HTML_TAG_RE.finditer(text):
        start, end = m.span()
        # Escape the plain-text segment before this tag
        if start > last_end:
            parts.append(_html.escape(text[last_end:start], quote=False))

        if m.group("ahref") is not None:
            # Matched <a href="...">text</a> — preserve tag + escape inner text
            parts.append(f'<{m.group("ahref")}>')
            parts.append(_html.escape(m.group("atext"), quote=False))
            parts.append("</a>")
        else:
            # Matched simple self-closing or paired tag — preserve as-is
            parts.append(f'<{m.group("tag")}>')

        last_end = end

    # Escape trailing plain text
    if last_end < len(text):
        parts.append(_html.escape(text[last_end:], quote=False))

    return "".join(parts)


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
    _chat_message_ids: dict[int, list[int]] = {}  # tracked message IDs per chat for /clear deletion

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
        # Streaming state for live response updates
        self._streaming_buffers: dict[str, str] = {}
        self._streaming_meta: dict[str, dict] = {}
        # Progress bar + typing indicator persistence
        self._progress_active: set[str] = set()   # task_ids with active progress updaters
        self._streaming_active: set[str] = set()  # task_ids where streaming editor has kicked in
        # Load persisted tracked messages so /clear works across restarts
        TelegramBot._load_tracked_messages()

    # ── Message tracking for /clear ─────────────────────────────────────────

    @classmethod
    def _get_tracked_messages_path(cls):
        return settings.project_root / "data" / "telegram_tracked_messages.json"

    @classmethod
    def _load_tracked_messages(cls) -> None:
        """Load tracked message IDs from disk so they survive restarts."""
        try:
            path = cls._get_tracked_messages_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cls._chat_message_ids = {int(k): v for k, v in data.items()}
        except Exception:
            pass

    @classmethod
    def _save_tracked_messages(cls) -> None:
        """Persist tracked message IDs to disk."""
        try:
            path = cls._get_tracked_messages_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {str(k): v for k, v in cls._chat_message_ids.items()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    @classmethod
    def _track_message(cls, chat_id: int, message_id: int) -> None:
        """Track a message ID for a chat so it can be deleted via /clear.

        Keeps only the last 1000 message IDs per chat to prevent unbounded memory.
        Persists to disk so tracked messages survive server restarts.
        """
        if chat_id not in cls._chat_message_ids:
            cls._chat_message_ids[chat_id] = []
        # Deduplicate to avoid redundant delete API calls
        if message_id not in cls._chat_message_ids[chat_id]:
            cls._chat_message_ids[chat_id].append(message_id)
        # Prune to last 1000
        if len(cls._chat_message_ids[chat_id]) > 1000:
            cls._chat_message_ids[chat_id] = cls._chat_message_ids[chat_id][-1000:]
        cls._save_tracked_messages()

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

        # Register command menu (best-effort)
        await self._register_commands()

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

                    edited_message = update.get("edited_message")
                    if edited_message is not None:
                        await self._handle_edited_message(edited_message)

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
            "allowed_updates": ["message", "edited_message"],
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

    async def _register_commands(self) -> None:
        """Register the bot's command menu with Telegram so users see autocomplete suggestions."""
        url = TELEGRAM_API_BASE.format(token=self.token, method="setMyCommands")
        payload = {
            "commands": [
                {"command": "start", "description": "Show welcome message"},
                {"command": "help", "description": "Show available commands"},
                {"command": "clear", "description": "Clear all messages and context"},
                {"command": "auth", "description": "Authenticate with PIN: /auth <PIN>"},
            ]
        }
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        logger.info("Telegram bot: command menu registered")
                        return
                    else:
                        logger.warning("Telegram API error (setMyCommands): {}", data.get("description", "unknown"))
                else:
                    logger.warning("Telegram API HTTP {} (setMyCommands): {}", response.status_code, response.text[:200])
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable (setMyCommands): {}", exc)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
        logger.warning("Telegram bot: failed to register command menu after {} attempts", MAX_RETRIES)

    async def _send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Send a chat action (e.g., typing indicator) to a Telegram chat.

        Args:
            chat_id: Target chat ID.
            action: Action type — "typing", "upload_photo", "record_video", etc.

        Returns True on success, False on failure.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="sendChatAction")
        payload = {
            "chat_id": chat_id,
            "action": action,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return True
                    else:
                        logger.warning(
                            "Telegram API error (sendChatAction): {}",
                            data.get("description", "unknown"),
                        )
                        return False
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                    logger.warning(
                        "Telegram rate limited (sendChatAction): retry after {}s",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning(
                        "Telegram API HTTP {} (sendChatAction): {}",
                        response.status_code,
                        response.text[:200],
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable (sendChatAction): {}", exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
        return False

    async def _set_message_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str,
        is_big: bool = False,
    ) -> bool:
        """Set an emoji reaction on a user's message via setMessageReaction.

        Args:
            chat_id: Target chat ID.
            message_id: The message to react to (user's original message).
            emoji: Emoji string, e.g. "🤔" or "✅".
            is_big: Whether to show the reaction as a big animated reaction.

        Returns True on success, False on failure (silently — reactions are best-effort).
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="setMessageReaction")
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
            "is_big": is_big,
        }
        try:
            response = await self._client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return True
                logger.debug(
                    "Telegram API error (setMessageReaction emoji={}): {}",
                    emoji, data.get("description", "unknown"),
                )
            else:
                logger.debug(
                    "Telegram API HTTP {} (setMessageReaction emoji={}): {}",
                    response.status_code, emoji, response.text[:100],
                )
        except httpx.RequestError as exc:
            logger.debug("Telegram API unreachable (setMessageReaction): {}", exc)
        return False

    async def _download_file(self, file_id: str) -> bytes | None:
        """Download a file from Telegram by file_id using getFile + download.

        Returns raw bytes, or None on failure.
        """
        url = TELEGRAM_API_BASE.format(token=self.token, method="getFile")
        params = {"file_id": file_id}

        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        file_path = data["result"].get("file_path")
                        if file_path:
                            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
                            dl_resp = await self._client.get(download_url, timeout=httpx.Timeout(30.0))
                            if dl_resp.status_code == 200:
                                return dl_resp.content
                            else:
                                logger.warning("Telegram bot: download file HTTP {}", dl_resp.status_code)
                        else:
                            logger.warning("Telegram bot: getFile returned no file_path")
                    else:
                        logger.warning("Telegram bot: getFile API error: {}", data.get("description", "unknown"))
                else:
                    logger.warning("Telegram bot: getFile HTTP {}", resp.status_code)
            except httpx.RequestError as exc:
                logger.warning("Telegram bot: download error: {}", exc)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
        return None

    async def send_media(
        self,
        chat_id: int,
        media_type: str,
        file_data: bytes,
        filename: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> int | None:
        """Send a media file to a Telegram chat using multipart/form-data upload.

        Args:
            chat_id: Target chat ID.
            media_type: One of "photo", "document", "voice", "video", "audio", "sticker", "video_note".
            file_data: Raw bytes of the file.
            filename: Human-readable filename (e.g. "image.png", "audio.ogg").
            caption: Optional caption text.
            reply_to_message_id: Optional message ID to reply to.

        Returns the message_id on success, None on failure.
        """
        method_map = {
            "photo": "sendPhoto",
            "document": "sendDocument",
            "voice": "sendVoice",
            "video": "sendVideo",
            "audio": "sendAudio",
            "sticker": "sendSticker",
            "video_note": "sendVideoNote",
        }

        method = method_map.get(media_type)
        if not method:
            logger.warning("Telegram bot: unknown media type '{}'", media_type)
            return None

        url = TELEGRAM_API_BASE.format(token=self.token, method=method)

        fields: dict[str, Any] = {
            "chat_id": str(chat_id),
        }
        if caption:
            fields["caption"] = caption
        if reply_to_message_id is not None:
            fields["reply_to_message_id"] = str(reply_to_message_id)

        files = {
            media_type: (filename, file_data),
        }

        await self._rate_limiter.wait_if_needed(chat_id)

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, data=fields, files=files)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        self._rate_limiter.record_send(chat_id)
                        result = data.get("result", {})
                        msg_id = result.get("message_id")
                        if msg_id is not None:
                            self._track_message(chat_id, msg_id)
                        return msg_id
                    else:
                        logger.warning("Telegram API error ({}): {}", method, data.get("description", "unknown"))
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                    logger.warning("Telegram rate limited ({}): retry after {}s", method, retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning("Telegram API HTTP {} ({}): {}", response.status_code, method, response.text[:200])
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
            except httpx.RequestError as exc:
                logger.warning("Telegram API unreachable ({}): {}", method, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
        return None

    async def _send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> int | None:
        """Send a text message to a Telegram chat.

        Args:
            chat_id: Target chat ID.
            text: Message text to send.
            reply_to_message_id: If set, the message will reply to the given message.

        Returns the message_id on success, None on failure.
        """
        # Show typing indicator before sending
        await self._send_chat_action(chat_id, action="typing")

        # Auto-split if HTML-escaped text would exceed Telegram's 4096-char limit
        _escaped_preview = _escape_html(_markdown_to_telegram_html(text))
        if len(_escaped_preview) > 4090:
            chunks = self._split_text_for_telegram(text, max_len=3800)
            last_id: int | None = None
            for i, chunk in enumerate(chunks):
                chunk_reply = reply_to_message_id if i == 0 else None
                chunk_id = await self._send_message(chat_id, chunk, reply_to_message_id=chunk_reply)
                if chunk_id is not None:
                    last_id = chunk_id
            return last_id

        url = TELEGRAM_API_BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": chat_id,
            "text": _escape_html(_markdown_to_telegram_html(text)),
            "parse_mode": "HTML",
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        await self._rate_limiter.wait_if_needed(chat_id)
        # Re-send typing right before the actual POST so it stays visible
        await self._send_chat_action(chat_id, action="typing")

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        self._rate_limiter.record_send(chat_id)
                        result = data.get("result", {})
                        message_id = result.get("message_id")
                        if message_id is not None:
                            self._track_message(chat_id, message_id)
                        return message_id
                    else:
                        desc = data.get("description", "unknown")
                        # "message is not modified" can also happen on sendMessage
                        # if Telegram deduplicates — treat as success
                        if "message is not modified" in desc.lower():
                            return None  # no new message_id, but not an error
                        # If the message we're replying to was deleted (e.g. by /clear),
                        # retry without reply_to_message_id
                        if "message to be replied not found" in desc.lower() and reply_to_message_id is not None:
                            logger.info(
                                "Telegram bot: reply target {} was deleted, retrying without reply",
                                reply_to_message_id,
                            )
                            payload.pop("reply_to_message_id", None)
                            reply_to_message_id = None
                            continue
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
            "text": _escape_html(_markdown_to_telegram_html(text)) if parse_mode else text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

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
                        desc = data.get("description", "unknown")
                        # "message is not modified" means the edit succeeded
                        # but the content was identical — treat as success
                        if "message is not modified" in desc.lower():
                            self._rate_limiter.record_send(chat_id)
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

    async def _delete_messages(self, chat_id: int, message_ids: list[int]) -> dict:
        """Delete messages from a Telegram chat using individual deleteMessage calls.

        Uses the singular deleteMessage API (not the batch deleteMessages) for
        broader compatibility. Processes messages sequentially with a small delay
        between deletions to avoid rate limits. Handles errors per-message so a
        single expired message doesn't block the entire batch.

        Args:
            chat_id: Target chat ID.
            message_ids: List of message IDs to delete.

        Returns a dict with keys: deleted, not_found, too_old, other_error.
        """
        result = {"deleted": 0, "not_found": 0, "too_old": 0, "other_error": 0}
        if not message_ids:
            return result

        total = len(message_ids)

        for i, msg_id in enumerate(message_ids):
            url = TELEGRAM_API_BASE.format(token=self.token, method="deleteMessage")
            payload = {
                "chat_id": chat_id,
                "message_id": msg_id,
            }

            for attempt in range(MAX_RETRIES):
                try:
                    response = await self._client.post(url, json=payload)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("ok"):
                            result["deleted"] += 1
                            break
                        else:
                            desc = data.get("description", "unknown")
                            # "message can't be deleted" — too old, already deleted, or no permission
                            if "can't delete" in desc.lower():
                                result["too_old"] += 1
                                logger.debug(
                                    "Telegram bot: can't delete message {} in chat {}: {}",
                                    msg_id, chat_id, desc,
                                )
                                break
                            result["other_error"] += 1
                            logger.debug(
                                "Telegram API error (deleteMessage) for msg {}: {}",
                                msg_id, desc,
                            )
                            break
                    elif response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                        logger.warning(
                            "Telegram rate limited (deleteMessage): retry after {}s",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    elif response.status_code == 400:
                        desc = response.text[:200]
                        # "message to delete not found" or "message not found"
                        if "not found" in desc.lower():
                            result["not_found"] += 1
                        elif "can't delete" in desc.lower():
                            result["too_old"] += 1
                        else:
                            result["other_error"] += 1
                        logger.debug(
                            "Telegram API 400 (deleteMessage) for msg {}: {} — skipping",
                            msg_id, desc,
                        )
                        break
                    elif response.status_code == 403:
                        result["other_error"] += 1
                        logger.debug(
                            "Telegram API 403 (deleteMessage) for msg {}: {} — skipping",
                            msg_id, response.text[:200],
                        )
                        break
                    else:
                        logger.warning(
                            "Telegram API HTTP {} (deleteMessage) for msg {}: {}",
                            response.status_code, msg_id, response.text[:200],
                        )
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        result["other_error"] += 1
                        break
                except httpx.RequestError as exc:
                    logger.warning(
                        "Telegram API unreachable (deleteMessage) for msg {}: {}",
                        msg_id, exc,
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    result["other_error"] += 1
                    break

            # Small delay between individual deletions to avoid hitting rate limits
            if i < total - 1:
                await asyncio.sleep(0.05)

        logger.info(
            "Telegram bot: deleted {}/{} messages in chat {} "
            "(not_found={}, too_old={}, other_error={})",
            result["deleted"], total, chat_id,
            result["not_found"], result["too_old"], result["other_error"],
        )
        return result

    # ── Progress bar updater ────────────────────────────────────────────────

    async def _progress_updater_loop(
        self, task_id: str, chat_id: int, msg_id: int, start_time: float,
    ) -> None:
        """Background loop that edits the ack message with a progress bar every 5s.

        Runs until cancelled or task_id is removed from _progress_active.
        Skips updates if streaming has started for this task_id.
        Sends typing action before each edit to keep the indicator alive.
        All exceptions are silently swallowed (best-effort).
        """
        spinners = ["◐", "◓", "◑", "◒"]
        bar_width = 15
        spinner_idx = 0

        while task_id in self._progress_active:
            # Stop if streaming has kicked in
            if task_id in self._streaming_active:
                self._progress_active.discard(task_id)
                break

            await asyncio.sleep(5.0)

            # Re-check conditions after sleep
            if task_id not in self._progress_active:
                break
            if task_id in self._streaming_active:
                self._progress_active.discard(task_id)
                break

            try:
                elapsed = _time.monotonic() - start_time
                spinner = spinners[spinner_idx % len(spinners)]
                spinner_idx += 1

                # Calculate bar fill — capped at 95% of TASK_TIMEOUT
                fraction = min(elapsed / TASK_TIMEOUT, 0.95)
                filled = int(fraction * bar_width)
                bar = "▓" * filled + "░" * (bar_width - filled)

                progress_text = (
                    f"⏳ Processing... {spinner}\n"
                    f"<code>[{bar}]</code> {int(elapsed)}s elapsed"
                )

                # Keep typing indicator alive
                await self._send_chat_action(chat_id, action="typing")
                await self._edit_message(chat_id, msg_id, progress_text)
            except Exception:
                # Best-effort — swallow all errors
                pass

    # ── Streaming helpers ───────────────────────────────────────────────────

    def start_streaming_task(self, task_id: str, chat_id: int, message_id: int) -> None:
        """Initialize streaming state for a task.

        Note: _streaming_active is NOT set here — it's set lazily in
        append_streaming_text() when the first real token arrives, so the
        progress bar can keep ticking until actual text shows up.
        """
        self._streaming_buffers[task_id] = ""
        self._streaming_meta[task_id] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "last_len": 0,
            "is_done": False,
        }

    def append_streaming_text(self, task_id: str, text: str) -> None:
        """Append text to the streaming buffer for a task.

        Marks streaming as active on first real token so the progress bar
        updater stops and the streaming editor takes over.
        """
        if task_id in self._streaming_buffers:
            # Mark streaming active lazily — only when real text arrives
            self._streaming_active.add(task_id)
            self._streaming_buffers[task_id] += text
            logger.debug(
                "Telegram bot: appended {} chars to stream buffer for task {} (total {} chars)",
                len(text), task_id[:8], len(self._streaming_buffers[task_id]),
            )

    def finalize_streaming_task(self, task_id: str) -> None:
        """Mark a streaming task as done so the editor loop exits."""
        self._streaming_active.discard(task_id)
        self._progress_active.discard(task_id)
        if task_id in self._streaming_meta:
            self._streaming_meta[task_id]["is_done"] = True

    async def _stream_editor_loop(self, task_id: str) -> str | None:
        """Background coroutine that periodically edits the Telegram message with accumulated text.

        Returns the final accumulated text, or None if task_id not found.
        """
        meta = self._streaming_meta.get(task_id)
        if not meta:
            return None

        chat_id = meta["chat_id"]
        message_id = meta["message_id"]
        logger.info(
            "Telegram bot: stream editor started for task {} (msg_id={})",
            task_id[:8], message_id,
        )

        while not meta["is_done"]:
            await asyncio.sleep(1.5)

            # Keep typing indicator alive while generating
            await self._send_chat_action(chat_id, action="typing")

            current_text = self._streaming_buffers.get(task_id, "")
            # Only edit if there's significant new content (avoid empty/noisy edits)
            if len(current_text) > meta["last_len"] + 5:
                # Telegram editMessageText hard limit is 4096 chars.
                # Show the beginning of the response so the user sees context,
                # not a trailing window. Full content is split into multiple
                # messages after streaming completes.
                if len(current_text) > 3900:
                    # Don't show truncated content — show progress indicator only
                    # to avoid confusing partial text with the final response
                    display = (
                        f"⏳ <b>Generating long response...</b>\n"
                        f"<code>[{len(current_text):,} chars so far]</code>"
                    )
                else:
                    display = current_text + "\n\n<i>⏳ Generating...</i>"

                try:
                    success = await self._edit_message(chat_id, message_id, display)
                    if success:
                        meta["last_len"] = len(current_text)
                        logger.debug(
                            "Telegram bot: stream edit OK for task {} ({} chars)",
                            task_id[:8], len(current_text),
                        )
                    else:
                        logger.warning(
                            "Telegram bot: stream edit returned False for task {}",
                            task_id[:8],
                        )
                except Exception as exc:
                    logger.warning(
                        "Telegram bot: stream edit failed for task {}: {}",
                        task_id[:8], exc,
                    )

        # Short-text optimization: if the final text is short (<100 chars),
        # skip the streaming edits entirely and just edit once at the end.
        # This avoids flicker for quick responses like "OK" or "Done."
        final_text = self._streaming_buffers.get(task_id, "")
        if len(final_text) < 100 and meta["last_len"] == 0:
            display = final_text
            try:
                await self._edit_message(chat_id, message_id, display)
            except Exception:
                pass

        # Return final text and cleanup
        final_text = self._streaming_buffers.pop(task_id, "")
        self._streaming_meta.pop(task_id, None)
        logger.info(
            "Telegram bot: stream editor finished for task {} (final {} chars, edits={})",
            task_id[:8], len(final_text), meta.get("last_len", 0),
        )
        return final_text

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

    @staticmethod
    def _extract_media_info(msg: dict) -> str:
        """Extract a human-readable description of media in a Telegram message.

        Returns a string like "📷 Photo (1920x1080, 340KB)" or "📄 Document: report.pdf (2MB)".
        Returns empty string if no media is found.
        """
        def _fmt_size(size: int) -> str:
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size/1024:.0f}KB"
            else:
                return f"{size/1024/1024:.1f}MB"

        # Photo
        photos = msg.get("photo")
        if photos:
            largest = photos[-1]
            w, h = largest.get("width", 0), largest.get("height", 0)
            size = largest.get("file_size", 0)
            return f"📷 Photo ({w}x{h}, {_fmt_size(size)})"

        # Document
        doc = msg.get("document")
        if doc:
            name = doc.get("file_name", "unknown")
            size = doc.get("file_size", 0)
            return f"📄 Document: {name} ({_fmt_size(size)})"

        # Voice
        if msg.get("voice"):
            return "🎤 Voice message"

        # Video
        video = msg.get("video")
        if video:
            w, h = video.get("width", 0), video.get("height", 0)
            dur = video.get("duration", 0)
            size = video.get("file_size", 0)
            return f"🎬 Video ({w}x{h}, {dur}s, {_fmt_size(size)})"

        # Audio
        audio = msg.get("audio")
        if audio:
            dur = audio.get("duration", 0)
            size = audio.get("file_size", 0)
            title = audio.get("title") or audio.get("performer") or ""
            base = f"🎵 Audio ({dur}s, {_fmt_size(size)})"
            return f"{base} — {title}" if title else base

        # Sticker
        sticker = msg.get("sticker")
        if sticker:
            emoji = sticker.get("emoji", "")
            anim = "🎭 Animated sticker" if sticker.get("is_animated") else "🎭 Sticker"
            return f"{anim} {emoji}" if emoji else anim

        # Video note
        if msg.get("video_note"):
            return "🎥 Video note (circular)"

        # Animation (GIF)
        if msg.get("animation"):
            return "🎞️ GIF/Animation"

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
        # Extract text (caption for media, text for text messages)
        text = (msg.get("text") or msg.get("caption") or "").strip()

        # Check if message has media content
        has_media = any(k in msg for k in ("photo", "document", "voice", "video", "audio", "sticker", "video_note", "animation"))

        # Generate media description if present
        media_desc = self._extract_media_info(msg) if has_media else ""

        # If there's media but no text, use the media description as the text
        if has_media and not text:
            text = media_desc
        elif has_media and text and media_desc:
            text = f"📎 {media_desc}\n\n{text}"

        # If no text AND no media, skip
        if not chat_id:
            return
        if not text and not has_media:
            return

        # Message-level dedup: Telegram guarantees at-least-once delivery.
        # Even with update_id dedup, a restart can cause the same message
        # to arrive under a different update_id. Use (chat_id, message_id)
        # as a second dedup layer shared across all instances.
        message_id = msg.get("message_id")
        if chat_id is not None and message_id is not None:
            # Track incoming message for potential /clear deletion
            self._track_message(chat_id, message_id)

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
                await self._handle_auth(chat_id, text, reply_to_message_id=message_id)
            else:
                await self._send_message(
                    chat_id,
                    "🔒 <b>Authentication required.</b>\n\n"
                    "Send <code>/auth <PIN></code> to authenticate.\n\n"
                    "Don't have the PIN? Contact the bot owner.",
                    reply_to_message_id=message_id,
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
            await self._handle_command(chat_id, text, reply_to_message_id=message_id)
            return

        # Download media if present
        media_file = None
        media_type = None
        media_filename = None

        if has_media:
            file_id = None
            file_ext = ""

            if msg.get("photo"):
                photos = msg["photo"]
                file_id = photos[-1].get("file_id")
                file_ext = ".jpg"
                media_type = "photo"
                media_filename = f"photo_{message_id}.jpg"

            elif msg.get("document"):
                doc = msg["document"]
                file_id = doc.get("file_id")
                file_ext = ".bin"
                media_type = "document"
                # Try to preserve original filename
                orig_name = doc.get("file_name", f"document_{message_id}")
                media_filename = orig_name
                # Determine extension from mime type if no file_name
                mime = doc.get("mime_type", "")
                if not doc.get("file_name"):
                    media_filename = f"document_{message_id}"
                    if "pdf" in mime:
                        media_filename += ".pdf"
                    elif "zip" in mime:
                        media_filename += ".zip"
                    elif "text" in mime:
                        media_filename += ".txt"

            elif msg.get("voice"):
                voice = msg["voice"]
                file_id = voice.get("file_id")
                media_type = "voice"
                media_filename = f"voice_{message_id}.ogg"

            elif msg.get("video"):
                video = msg["video"]
                file_id = video.get("file_id")
                media_type = "video"
                media_filename = f"video_{message_id}.mp4"

            elif msg.get("audio"):
                audio = msg["audio"]
                file_id = audio.get("file_id")
                media_type = "audio"
                orig_name = audio.get("file_name", "")
                if orig_name:
                    media_filename = orig_name
                else:
                    media_filename = f"audio_{message_id}.mp3"

            elif msg.get("sticker"):
                sticker = msg["sticker"]
                file_id = sticker.get("file_id")
                file_ext = ".webp"
                media_type = "sticker"
                media_filename = f"sticker_{message_id}.webp"

            elif msg.get("video_note"):
                vn = msg["video_note"]
                file_id = vn.get("file_id")
                media_type = "video_note"
                media_filename = f"video_note_{message_id}.mp4"

            elif msg.get("animation"):
                anim = msg["animation"]
                file_id = anim.get("file_id")
                media_type = "animation"
                orig_name = anim.get("file_name", "")
                media_filename = orig_name if orig_name else f"animation_{message_id}.gif"

            if file_id:
                logger.info("Telegram bot: downloading {} media (file_id={})", media_type, file_id[:16])
                media_file = await self._download_file(file_id)
                if media_file:
                    logger.info("Telegram bot: downloaded {} ({} bytes)", media_filename, len(media_file))
                else:
                    logger.warning("Telegram bot: failed to download media file_id={}", file_id[:16])

        # Regular message — forward to Master via task_queue
        await self._send_chat_action(chat_id, action="typing")
        await self._handle_user_message(
            chat_id, text,
            reply_to_message_id=message_id,
            media_file=media_file,
            media_type=media_type,
            media_filename=media_filename,
        )

    async def _handle_edited_message(self, msg: dict) -> None:
        """Process an edited message — re-queue the updated text as a new task.

        Edited messages (message edits / typo corrections) are treated as new
        tasks but tagged with "(edited)" so Master can incorporate the previous
        context if desired.
        """
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "")
        text = (msg.get("text") or "").strip()
        message_id = msg.get("message_id")

        if not chat_id or not text:
            return

        # Only respond in private chats (same as _handle_message's auth/group logic)
        # Don't respond to edits in groups unless the original was a command.
        if chat_type not in ("private",):
            return

        # Authentication check
        if self._auth.enabled and not self._auth.is_authorized(chat_id):
            return  # Don't acknowledge edits from unauthenticated users

        # Tag the text so Master knows it's an edit
        text = f"(edited) {text}"

        # Send brief ack
        await self._send_chat_action(chat_id, action="typing")
        await self._handle_user_message(
            chat_id, text,
            reply_to_message_id=message_id,
        )

    async def _clear_session(self, session_id: str) -> None:
        """Delete session data from DB and disk for a given session_id."""
        # 1. Remove queued tasks
        deleted = clear_session_tasks(session_id, source="telegram")
        logger.info("Telegram bot: cleared {} task_queue rows for session {}", deleted, session_id)

        # 2. Remove session event files
        session_events_dir = settings.project_root / "data" / "sessions" / session_id
        if session_events_dir.exists():
            import shutil
            shutil.rmtree(session_events_dir, ignore_errors=True)
            logger.info("Telegram bot: removed session events dir {}", session_events_dir)

        # 3. Remove session summary files in master/sessions
        master_sessions_dir = settings.agents_dir / "master" / "sessions"
        if master_sessions_dir.exists():
            for f in master_sessions_dir.iterdir():
                if f.name.startswith(session_id):
                    try:
                        f.unlink()
                        logger.info("Telegram bot: removed session file {}", f)
                    except Exception:
                        pass

    async def _handle_command(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
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
                "/clear — Clear all messages and context for this chat\n"
                "/auth <PIN> — Authenticate with the bot\n\n"
                "<b>How it works:</b>\n"
                "1. You send a message\n"
                "2. It's queued for the Master agent\n"
                "3. Master processes it and sends the response back\n\n"
                "<i>Responses may take a few seconds depending on workload.</i>"
            )
            await self._send_message(chat_id, welcome, reply_to_message_id=reply_to_message_id)
        elif command == "/clear":
            await self._clear_session(str(chat_id))

            # Delete tracked messages from the Telegram chat
            raw_ids = TelegramBot._chat_message_ids.pop(chat_id, [])
            # Deduplicate while preserving order
            seen: set[int] = set()
            message_ids = [mid for mid in raw_ids if not (mid in seen or seen.add(mid))]

            stats: dict = {"deleted": 0, "not_found": 0, "too_old": 0, "other_error": 0}
            if message_ids:
                stats = await self._delete_messages(chat_id, message_ids)
                logger.info(
                    "Telegram bot: /clear — deleted {}/{} tracked messages in chat {} "
                    "(not_found={}, too_old={}, other_error={})",
                    stats["deleted"], len(message_ids), chat_id,
                    stats["not_found"], stats["too_old"], stats["other_error"],
                )
            else:
                logger.info("Telegram bot: /clear — no tracked messages for chat {}", chat_id)

            # Persist the cleared state
            TelegramBot._save_tracked_messages()

            # Build informative confirmation based on actual results
            total = len(message_ids)
            deleted = stats["deleted"]
            failed = total - deleted
            if total == 0:
                confirm_text = (
                    "🧹 <b>Chat context cleared.</b>\n\n"
                    "No tracked messages to delete. The conversation starts fresh."
                )
            elif deleted == total:
                confirm_text = (
                    f"🧹 <b>Chat cleared.</b>\n\n"
                    f"Deleted {deleted} message{'s' if deleted != 1 else ''}.\n"
                    f"The conversation starts fresh from here."
                )
            else:
                reasons: list[str] = []
                if stats["too_old"]:
                    reasons.append(f"{stats['too_old']} too old")
                if stats["not_found"]:
                    reasons.append(f"{stats['not_found']} already gone")
                if stats["other_error"]:
                    reasons.append(f"{stats['other_error']} permission/network error")
                reason_str = ", ".join(reasons) if reasons else "unknown reason"
                confirm_text = (
                    f"🧹 <b>Chat partially cleared.</b>\n\n"
                    f"Deleted {deleted} of {total} tracked messages.\n"
                    f"{failed} couldn't be removed ({reason_str}).\n\n"
                    f"<i>Telegram doesn't allow bots to delete user messages older than 48 hours.</i>\n\n"
                    f"The conversation starts fresh from here."
                )

            # Send confirmation AFTER deleting tracked messages.
            # Remove this confirmation message from tracking so it won't
            # be deleted by the next /clear — it should remain visible.
            confirmation_msg_id = await self._send_message(chat_id, confirm_text)
            if confirmation_msg_id is not None:
                # Untrack the confirmation message so /clear leaves it visible
                ids = TelegramBot._chat_message_ids.get(chat_id, [])
                if confirmation_msg_id in ids:
                    ids.remove(confirmation_msg_id)
                    TelegramBot._save_tracked_messages()
        else:
            await self._send_message(
                chat_id,
                f"Unknown command: {command}\n\nSend /help to see available commands.",
                reply_to_message_id=reply_to_message_id,
            )

    async def _handle_auth(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        """Handle /auth command — authenticate a user."""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send_message(
                chat_id,
                "🔒 Usage: <code>/auth <PIN></code>\n\n"
                "Example: <code>/auth 1234</code>",
                reply_to_message_id=reply_to_message_id,
            )
            return

        provided_pin = parts[1].strip()
        if self._auth.authenticate(chat_id, provided_pin):
            await self._send_message(
                chat_id,
                "✅ <b>Authentication successful!</b>\n\n"
                "You can now send messages to the bot.\n\n"
                "Send /help to see available commands.",
                reply_to_message_id=reply_to_message_id,
            )
            logger.info("Telegram bot: chat {} authenticated successfully", chat_id)
        else:
            await self._send_message(
                chat_id,
                "❌ <b>Invalid PIN.</b> Please try again.\n\n"
                "Usage: <code>/auth <PIN></code>",
                reply_to_message_id=reply_to_message_id,
            )
            logger.warning("Telegram bot: failed auth attempt from chat {}", chat_id)

    @staticmethod
    def _split_text_for_telegram(text: str, max_len: int = 4000) -> list[str]:
        """Split long text into chunks suitable for Telegram's per-message limit.

        Splits at paragraph boundaries (double newline) first, then single
        newlines, then spaces, then hard character boundaries. Avoids splitting
        inside markdown code blocks if possible.

        Args:
            text: The text to split.
            max_len: Maximum length per chunk (default 4000, Telegram's limit is 4096).

        Returns:
            A list of text chunks, each <= max_len characters.
        """
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        remaining = text

        while len(remaining) > max_len:
            # Find code block boundaries in the current remaining text
            # We'll try to split at paragraph/newline boundaries first.
            # Take the first max_len characters as our candidate region.
            candidate = remaining[:max_len]

            # Try splitting at paragraph boundary (\n\n) — prefer clean breaks
            para_split = candidate.rfind("\n\n")
            if para_split > 0:
                chunks.append(remaining[:para_split])
                remaining = remaining[para_split:]
                continue

            # Try splitting at single newline
            newline_split = candidate.rfind("\n")
            if newline_split > 0:
                chunks.append(remaining[:newline_split])
                remaining = remaining[newline_split:]
                continue

            # Try splitting at space
            space_split = candidate.rfind(" ")
            if space_split > 0:
                chunks.append(remaining[:space_split])
                remaining = remaining[space_split:]
                continue

            # Fall back to hard split at max_len
            chunks.append(remaining[:max_len])
            remaining = remaining[max_len:]

        # Append any remaining text
        if remaining:
            chunks.append(remaining)

        return chunks

    async def _handle_user_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        media_file: bytes | None = None,
        media_type: str | None = None,
        media_filename: str | None = None,
    ) -> None:
        """Forward a user message to Master via task_queue and wait for result.

        Args:
            chat_id: Target chat ID.
            text: Message text to process.
            reply_to_message_id: If set, bot replies will reply to this message ID.
            media_file: Raw bytes of a downloaded media file (optional).
            media_type: Type of media ("photo", "document", "voice", etc.).
            media_filename: Original filename of the media.
        """
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

        # Vision safeguard — if an image is attached, verify master's model supports vision
        if media_file is not None and media_type in ("photo", "sticker"):
            try:
                import json as _json
                from pathlib import Path as _Path
                _settings_path = _Path(__file__).parents[2] / "config" / "agent-settings.json"
                _agent_cfg = _json.loads(_settings_path.read_text(encoding="utf-8"))
                _master_model = _agent_cfg.get("agents", {}).get("master", {}).get("model", "")
                if _master_model and _master_model not in VISION_CAPABLE_MODELS:
                    _vision_examples = sorted(VISION_CAPABLE_MODELS)[:6]
                    _err = (
                        f"⚠️ Current model <code>{_master_model}</code> does not support visual recognition.\n\n"
                        f"Available vision-capable models include:\n"
                        + "\n".join(f"• <code>{m}</code>" for m in _vision_examples)
                        + "\n\n<i>Switch master's model in Settings to use image recognition.</i>"
                    )
                    await self._send_message(chat_id, _err, reply_to_message_id=reply_to_message_id)
                    return
            except Exception as _ve:
                logger.warning("Telegram bot: vision capability check failed: {}", _ve)
                # Proceed anyway — don't block the user if the check itself errors

        # React with 🤔 to signal we're processing (fire-and-forget, best-effort)
        if reply_to_message_id is not None:
            asyncio.create_task(
                self._set_message_reaction(chat_id, reply_to_message_id, "🤔")
            )

        # Send immediate acknowledgment and capture message_id.
        # Retry up to 3 times to ensure we get a message_id for later editing.
        ack_msg_id = None
        for _attempt in range(3):
            ack_msg_id = await self._send_message(chat_id, "⏳ Processing your request...", reply_to_message_id=reply_to_message_id)
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
        metadata_parts = {}
        if reply_to_message_id is not None:
            metadata_parts["reply_to_message_id"] = reply_to_message_id
        if media_file is not None and media_filename is not None:
            # Save media to disk
            media_path = settings.project_root / "data" / "telegram_media" / f"{task_id}_{media_filename}"
            media_path.parent.mkdir(parents=True, exist_ok=True)
            media_path.write_bytes(media_file)
            metadata_parts["media_path"] = str(media_path)
            metadata_parts["media_type"] = media_type
            metadata_parts["media_filename"] = media_filename
            logger.info(
                "Telegram bot: saved media to {} ({} bytes)",
                media_path, len(media_file),
            )
            # Append media info to prompt text so Master sees it directly
            media_type_label = media_type or "file"
            text = f"{text}\n[📎 {media_type_label} attached: {media_path}]"
        metadata = json.dumps(metadata_parts) if metadata_parts else None

        try:
            create_queued_task(
                id=task_id,
                prompt=text,
                source="telegram",
                session_id=session_id,
                metadata=metadata,
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
                reply_to_message_id=reply_to_message_id,
            )
            return

        # Start progress bar updater — ticks every 5s until streaming kicks in or task done
        if ack_msg_id is not None:
            self._progress_active.add(task_id)
            asyncio.create_task(
                self._progress_updater_loop(task_id, chat_id, ack_msg_id, _time.monotonic())
            )

        # Start streaming — initialize buffer and spawn background editor
        if ack_msg_id is not None:
            self.start_streaming_task(task_id, chat_id, ack_msg_id)
            stream_task = asyncio.create_task(self._stream_editor_loop(task_id))
            logger.info(
                "Telegram bot: streaming started for task {} (ack_msg_id={})",
                task_id[:8], ack_msg_id,
            )
        else:
            stream_task = None
            logger.warning(
                "Telegram bot: no ack_msg_id — streaming disabled for task {}",
                task_id[:8],
            )

        # Wait for result
        result, result_metadata = await self._wait_for_result(task_id, chat_id)

        # Finalize streaming and wait for editor to finish
        if stream_task is not None:
            self.finalize_streaming_task(task_id)
            streamed_text = await stream_task
        else:
            streamed_text = None

        # Determine final text
        if result is not None:
            final_text = result
        elif streamed_text:
            final_text = streamed_text
        else:
            final_text = "❌ Sorry, the request timed out after 5 minutes. Please try again."

        # Check if the result includes media to send back
        media_path_from_result = None
        media_type_from_result = None
        if result_metadata:
            media_path_from_result = result_metadata.get("generate_media_path")
            media_type_from_result = result_metadata.get("generate_media_type", "document")

        if media_path_from_result:
            # Resolve relative to project root
            full_media_path = settings.project_root / media_path_from_result
            if full_media_path.exists():
                try:
                    file_data = full_media_path.read_bytes()
                    filename = full_media_path.name
                    logger.info(
                        "Telegram bot: sending media to chat {}: {} ({} bytes, type={})",
                        chat_id, media_path_from_result, len(file_data), media_type_from_result,
                    )
                    sent = await self.send_media(
                        chat_id,
                        media_type_from_result,
                        file_data,
                        filename,
                        caption=final_text,
                        reply_to_message_id=reply_to_message_id,
                    )
                    if sent is not None:
                        # Delete the ack message so the "⏳ Processing..." placeholder disappears
                        if ack_msg_id is not None:
                            await self._delete_messages(chat_id, [ack_msg_id])
                        # React ✅ after response is sent (fire-and-forget, best-effort)
                        if reply_to_message_id is not None:
                            asyncio.create_task(
                                self._set_message_reaction(chat_id, reply_to_message_id, "👍")
                            )
                        return  # Done — media sent with caption
                    logger.warning(
                        "Telegram bot: send_media failed for {} in chat {}",
                        media_path_from_result, chat_id,
                    )
                except Exception as exc:
                    logger.error(
                        "Telegram bot: error sending media {} to chat {}: {}",
                        media_path_from_result, chat_id, exc,
                    )
                    # Fall through to normal text response
            else:
                logger.warning(
                    "Telegram bot: media file not found: {} — falling back to text response",
                    media_path_from_result,
                )

        # Split long responses into multiple messages instead of truncating
        max_len = 3800
        if len(final_text) > max_len:
            # Delete the ack message so the "⏳ Processing..." placeholder disappears
            if ack_msg_id is not None:
                await self._delete_messages(chat_id, [ack_msg_id])
                ack_msg_id = None  # Prevent reuse below

            # Split into chunks and send as individual messages
            chunks = self._split_text_for_telegram(final_text, max_len)
            for i, chunk in enumerate(chunks):
                # Only reply to the original user message for the first chunk
                reply_to = reply_to_message_id if i == 0 else None
                await self._send_message(chat_id, chunk, reply_to_message_id=reply_to)
            # React ✅ after response is sent (fire-and-forget, best-effort)
            if reply_to_message_id is not None:
                asyncio.create_task(
                    self._set_message_reaction(chat_id, reply_to_message_id, "👍")
                )
            return  # Done — multiple messages sent

        # Try to edit the acknowledgment message with the final result
        if ack_msg_id is not None:
            edited = await self._edit_message(chat_id, ack_msg_id, final_text)
            if edited:
                if reply_to_message_id is not None:
                    asyncio.create_task(
                        self._set_message_reaction(chat_id, reply_to_message_id, "👍")
                    )
                return  # Success — only one message visible

            # HTML edit failed (likely HTML-unsafe characters) — try plain text
            edited = await self._edit_message(chat_id, ack_msg_id, final_text, parse_mode=None)
            if edited:
                if reply_to_message_id is not None:
                    asyncio.create_task(
                        self._set_message_reaction(chat_id, reply_to_message_id, "👍")
                    )
                return  # Success with plain text

        # Fall back to sending a new message — delete the ack (streaming state) first
        # then split into chunks so nothing is truncated
        if ack_msg_id is not None:
            await self._delete_messages(chat_id, [ack_msg_id])
            ack_msg_id = None
        fallback_chunks = self._split_text_for_telegram(final_text, max_len=3800)
        for i, chunk in enumerate(fallback_chunks):
            reply_to = reply_to_message_id if i == 0 else None
            await self._send_message(chat_id, chunk, reply_to_message_id=reply_to)
        if reply_to_message_id is not None:
            asyncio.create_task(
                self._set_message_reaction(chat_id, reply_to_message_id, "👍")
            )

    async def _wait_for_result(self, task_id: str, chat_id: int) -> tuple[str | None, dict | None]:
        """Poll task_queue for task completion.

        Polls every TASK_POLL_INTERVAL seconds, up to TASK_TIMEOUT seconds.
        Sends typing indicator periodically to keep the UI alive.

        Returns a tuple of (result_text, metadata_dict_or_None).
        The metadata dict is parsed from the task's JSON metadata field.
        """
        start = datetime.now(timezone.utc).timestamp()
        last_typing = 0.0

        # Show typing immediately so the user sees it even for fast responses
        await self._send_chat_action(chat_id, action="typing")
        last_typing = start

        while True:
            elapsed = datetime.now(timezone.utc).timestamp() - start
            if elapsed >= TASK_TIMEOUT:
                logger.warning(
                    "Telegram bot: task {} timed out after {}s",
                    task_id[:8], TASK_TIMEOUT,
                )
                return (None, None)

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
                metadata_raw = task.get("metadata")
                parsed_metadata = None
                if metadata_raw:
                    try:
                        parsed_metadata = json.loads(metadata_raw)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "Telegram bot: task {} has invalid metadata JSON: {!r:.100}",
                            task_id[:8], metadata_raw,
                        )
                logger.info(
                    "Telegram bot: task {} completed ({} chars, metadata={})",
                    task_id[:8], len(result), bool(parsed_metadata),
                )
                return (result, parsed_metadata)

            if status == "error":
                error_msg = task.get("error", "Unknown error")
                logger.warning("Telegram bot: task {} failed: {}", task_id[:8], error_msg)
                return (f"❌ An error occurred: {error_msg}", None)

            if status == "timeout":
                logger.warning("Telegram bot: task {} timed out in dispatcher", task_id[:8])
                return (None, None)

            # Still pending/running — keep polling and refresh typing indicator
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - last_typing >= 3.0:
                await self._send_chat_action(chat_id, action="typing")
                last_typing = now_ts

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
