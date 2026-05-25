# Telegram Bot Analysis — `app/backend/telegram_bot.py`

> Full file: 1831 lines, 79,995 bytes
> Generated: 2026-05-25

---

## 1. `allowed_updates` Configuration

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~375–380 (inside `_get_updates` method)

The `allowed_updates` parameter is passed to the `getUpdates` API call. It filters which types of updates the bot receives — currently set to `["message"]` only.

```python
# Line ~375-385 (inside _get_updates)
async def _get_updates(self, offset: int, timeout: int) -> list[dict] | None:
    """Call getUpdates with long-polling timeout.

    Returns the list of updates, or None on error.
    """
    url = TELEGRAM_API_BASE.format(token=self.token, method="getUpdates")
    params = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"],       # <── HERE: only message updates
    }
```

**Note:** `allowed_updates` is set to `["message"]`, meaning the bot only receives message-type updates. It does NOT receive:
- `callback_query` (inline button presses)
- `inline_query` (inline mode)
- `my_chat_member` / `chat_member` (permission changes)
- `channel_post` (channel posts)
- `edited_message` / `edited_channel_post`
- `poll` / `poll_answer`

---

## 2. Startup Section

### Bot Object Creation (FastAPI lifespan)

**File:** `app/backend/main.py`  
**Lines:** ~360-365 (inside `lifespan` async context manager)

```python
    # Start Telegram bot if configured.
    telegram_bot = None
    telegram_task = None
    if settings.telegram_enabled:
        from app.backend.telegram_bot import TelegramBot, set_telegram_bot_instance
        telegram_bot = TelegramBot(token=settings.telegram_bot_token)
        set_telegram_bot_instance(telegram_bot)
        telegram_task = asyncio.create_task(telegram_bot.start())
        logger.info("Telegram bot started (polling mode)")
```

The bot is created inside the FastAPI `lifespan` async context manager. It:
1. Checks `settings.telegram_enabled`
2. Instantiates `TelegramBot` with the token from settings
3. Registers the instance globally via `set_telegram_bot_instance()` (for tool access from agents)
4. Spawns `telegram_bot.start()` as an `asyncio.create_task()`

### Polling Loop Start (`TelegramBot.start()`)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~222-270 (the `start()` method)

```python
# Line ~222-270
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

        logger.info("Telegram bot: starting polling loop (token=...{})", ...)

        while self._running and not self._shutdown_event.is_set():
            try:
                updates = await self._get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
                if updates is None:
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        if update_id in self._processed_update_ids:
                            continue
                        self._processed_update_ids.add(update_id)
                        self._offset = update_id + 1

                    message = update.get("message")
                    if message is not None:
                        await self._handle_message(message)
```

Key architectural facts:
- Uses class-level `_instance_lock` and `_active_instance` to prevent duplicate polling across restarts
- The while-loop polls `_get_updates` with a 30s long-poll timeout
- Each update is deduplicated by `update_id` before processing
- Shutdown is signaled via `_shutdown_event` and HTTP client force-close

### Shutdown Section

**File:** `app/backend/main.py`  
**Lines:** ~400-415

```python
        # Shut the Telegram bot down BEFORE anything else awaitable so the
        # 30s long-poll doesn't keep uvicorn alive past the restart window.
        if telegram_bot is not None:
            try:
                await telegram_bot.stop()
            except Exception as _tg_stop_exc:
                logger.warning("Telegram bot stop() failed: {}", _tg_stop_exc)
        if telegram_task is not None:
            telegram_task.cancel()
            try:
                await telegram_task
            except (asyncio.CancelledError, Exception):
                pass
```

---

## 3. Streaming Code (~line 980 area)

### Streaming State Management

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~850-875 (streaming task init/meta)

```python
# Line ~850-875
    def start_streaming_task(self, task_id: str, chat_id: int, message_id: int) -> None:
        """Initialize streaming state for a task."""
        self._streaming_buffers[task_id] = ""
        self._streaming_meta[task_id] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "last_len": 0,
            "is_done": False,
        }

    def append_streaming_text(self, task_id: str, text: str) -> None:
        """Append text to the streaming buffer for a task."""
        if task_id in self._streaming_buffers:
            self._streaming_buffers[task_id] += text

    def finalize_streaming_task(self, task_id: str) -> None:
        """Mark a streaming task as done so the editor loop exits."""
        if task_id in self._streaming_meta:
            self._streaming_meta[task_id]["is_done"] = True
```

### `_stream_editor_loop` — Core Streaming Loop

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~877-965

```python
# Line ~877-965
    async def _stream_editor_loop(self, task_id: str) -> str | None:
        """Background coroutine that periodically edits the Telegram message with accumulated text.

        Returns the final accumulated text, or None if task_id not found.
        """
        meta = self._streaming_meta.get(task_id)
        if not meta:
            return None

        chat_id = meta["chat_id"]
        message_id = meta["message_id"]

        while not meta["is_done"]:
            await asyncio.sleep(1.5)

            # Keep typing indicator alive while generating
            await self._send_chat_action(chat_id, action="typing")

            current_text = self._streaming_buffers.get(task_id, "")
            # Only edit if there's significant new content (avoid empty/noisy edits)
            if len(current_text) > meta["last_len"] + 5:           # <── CHAR THRESHOLD = 5
                # Truncate for Telegram limit during streaming
                if len(current_text) > 3900:
                    display = current_text[:3900] + "\n\n<i>... (generating)</i>"
                else:
                    display = current_text + "\n\n<i>⏳ Generating...</i>"

                try:
                    success = await self._edit_message(chat_id, message_id, display)
                    if success:
                        meta["last_len"] = len(current_text)
                    else:
                        logger.warning("...")
                except Exception as exc:
                    logger.warning("...")

        # SHORT-TEXT OPTIMIZATION (line ~945):
        # If the final text is short (<100 chars), skip streaming edits
        # and just edit once at the end. Avoids flicker for quick responses.
        # Line ~945-950:
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
        return final_text
```

### Initial Message Send (Acknowledgment)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~1340-1360 (inside `_handle_user_message`)

```python
# Line ~1340-1360
        # Send immediate acknowledgment and capture message_id.
        # Retry up to 3 times to ensure we get a message_id for later editing.
        ack_msg_id = None
        for _attempt in range(3):
            ack_msg_id = await self._send_message(
                chat_id,
                "⏳ Processing your request...",
                reply_to_message_id=reply_to_message_id
            )
            if ack_msg_id is not None:
                break
            await asyncio.sleep(1)
```

Then streaming is started at lines ~1385-1395:

```python
# Line ~1385-1395
        # Start streaming — initialize buffer and spawn background editor
        if ack_msg_id is not None:
            self.start_streaming_task(task_id, chat_id, ack_msg_id)
            stream_task = asyncio.create_task(self._stream_editor_loop(task_id))
        else:
            stream_task = None
```

---

## 4. `_handle_message` Function

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~570-760 (full function)

First ~30 lines:

```python
# Line ~570-600
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
```

Continues with message-level dedup (~line 595-620):

```python
# Line ~595-620
        # Message-level dedup: Telegram guarantees at-least-once delivery.
        message_id = msg.get("message_id")
        if chat_id is not None and message_id is not None:
            self._track_message(chat_id, message_id)

            dedup_key = (chat_id, message_id)
            if dedup_key in TelegramBot._recent_message_ids:
                logger.warning(
                    "Telegram bot: duplicate message (chat={}, msg={}) — skipping",
                    chat_id, message_id,
                )
                return
            TelegramBot._recent_message_ids.add(dedup_key)
            if len(TelegramBot._recent_message_ids) > 5000:
                TelegramBot._recent_message_ids = set(
                    sorted(TelegramBot._recent_message_ids)[-2500:]
                )
```

Then forward prefix, auth check, chat type filtering, command handling, media download, and user message forwarding (lines ~620-760).

---

## 5. `_extract_media_info` Function

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~510-560

Full function:

```python
# Line ~510-560
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
```

---

## 6. Dedup Logic (All Four Layers)

The Telegram bot implements **four separate deduplication layers** to handle at-least-once delivery and restart overlaps:

### Layer 1: `update_id` dedup (polling loop)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~242-250 (within `start()` polling loop)

```python
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
```

**Shared across instances** via class-level variable (line ~195):
```python
    _processed_update_ids_global: set[int] = set()  # shared across instances
```

And in `__init__` (line ~206):
```python
        self._processed_update_ids: set[int] = TelegramBot._processed_update_ids_global
```

Pruning (lines ~255-257):
```python
                if len(self._processed_update_ids) > 1000:
                    self._processed_update_ids = set(sorted(self._processed_update_ids)[-500:])
```

### Layer 2: `(chat_id, message_id)` dedup (message-level)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~595-615 (inside `_handle_message`)

```python
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
```

Shared class-level set (line ~196):
```python
    _recent_message_ids: set[tuple[int, int]] = set()  # shared across instances
```

### Layer 3: `(chat_id, text)` dedup (instance-level, short window)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~1295-1320 (inside `_handle_user_message`)

```python
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
```

### Layer 4: Instance coordination (restart race prevention)

**File:** `app/backend/telegram_bot.py`  
**Lines:** ~230-260 (inside `start()`)

```python
        async with TelegramBot._instance_lock:
            old_instance = TelegramBot._active_instance
            if old_instance is not None and old_instance is not self:
                await old_instance.stop()
                # Wait up to 5s for old instance to fully exit
                for _ in range(50):
                    if not old_instance._running:
                        break
                    await asyncio.sleep(0.1)
            TelegramBot._active_instance = self
```

This prevents two bot instances from polling the same token simultaneously during restarts. Combined with:

- `stop()` force-closes the HTTP client (line ~305-315)
- Shared `_processed_update_ids_global` set survives across instances
- Shared `_recent_message_ids` set survives across instances

---

## Summary of Dedup Effectiveness

| Layer | Scope | Key | Window | Survives Restart? |
|-------|-------|-----|--------|-------------------|
| 1 | Class (all instances) | `update_id` | Last 500 IDs | ✅ (class-level) |
| 2 | Class (all instances) | `(chat_id, message_id)` | Last 2500 messages | ✅ (class-level) |
| 3 | Instance only | `(chat_id, text)` | 30 seconds | ❌ |
| 4 | Class lock | Instance handoff | During restart | ✅ (lock + wait) |
