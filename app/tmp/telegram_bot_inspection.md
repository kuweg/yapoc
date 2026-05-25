# Telegram Bot Inspection Report

**File:** `app/backend/telegram_bot.py` (1831 lines)
**Generated:** 2026-05-25

---

## 1. COMMAND HANDLERS

### Dispatch: `_handle_command()` (line ~796)

All commands are handled within `_handle_command(chat_id, text, reply_to_message_id)`. The command is extracted as:

```python
# Line 798
command = text.split()[0].lower()
```

### Registered Commands

| Command | Handler | Lines | Description |
|---------|---------|-------|-------------|
| `/start` | inline in `_handle_command` | 800–823 | Shows welcome message with command listings |
| `/help` | inline in `_handle_command` | 800–823 | Same handler as `/start` — same welcome text |
| `/clear` | inline in `_handle_command` | 824–888 | Clears session context + deletes tracked messages |
| `/auth <PIN>` | `_handle_auth()` | 890–922 | PIN-based authentication |

### Detail: `/start` and `/help` (lines 800–823)

```python
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
```

### Detail: `/clear` (lines 824–888)

`/clear` does three things:
1. Calls `_clear_session(str(chat_id))` — deletes SQLite task_queue rows + session event files + master session summary files
2. Deletes tracked Telegram messages (the bot's own messages) from the chat using `_delete_messages()`
3. Returns a confirmation message that is **untracked** so it survives the next `/clear`

```python
elif command == "/clear":
    await self._clear_session(str(chat_id))
    raw_ids = TelegramBot._chat_message_ids.pop(chat_id, [])
    # Deduplicate while preserving order
    seen: set[int] = set()
    message_ids = [mid for mid in raw_ids if not (mid in seen or seen.add(mid))]
    stats: dict = {"deleted": 0, "not_found": 0, "too_old": 0, "other_error": 0}
    if message_ids:
        stats = await self._delete_messages(chat_id, message_ids)
    # ...
    confirmation_msg_id = await self._send_message(chat_id, confirm_text)
    if confirmation_msg_id is not None:
        # Untrack the confirmation message so /clear leaves it visible
        ids = TelegramBot._chat_message_ids.get(chat_id, [])
        if confirmation_msg_id in ids:
            ids.remove(confirmation_msg_id)
            TelegramBot._save_tracked_messages()
```

### Detail: `/auth` via `_handle_auth()` (lines 890–922)

```python
async def _handle_auth(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await self._send_message(chat_id, "🔒 Usage: <code>/auth <PIN></code>...")
        return
    provided_pin = parts[1].strip()
    if self._auth.authenticate(chat_id, provided_pin):
        await self._send_message(chat_id, "✅ <b>Authentication successful!</b>...")
    else:
        await self._send_message(chat_id, "❌ <b>Invalid PIN.</b>...")
```

### Unknown commands (lines ~878–881)

```python
else:
    await self._send_message(
        chat_id,
        f"Unknown command: {command}\n\nSend /help to see available commands.",
        reply_to_message_id=reply_to_message_id,
    )
```

### `setMyCommands` — **NOT called anywhere**

The bot does **not** call `setMyCommands` to register the command list with Telegram. The command list is hardcoded in the welcome text only.

---

## 2. DEDUP LOGIC

There are **four** independent dedup layers:

### Layer 1: Update-level dedup via `_processed_update_ids` (lines ~244–248)

```python
# Line 244
if update_id in self._processed_update_ids:
    continue
self._processed_update_ids.add(update_id)
self._offset = update_id + 1
```

**Tracked field:** `update_id` (integer from Telegram's getUpdates response). **Pruning** at line ~276:

```python
if len(self._processed_update_ids) > 1000:
    self._processed_update_ids = set(sorted(self._processed_update_ids)[-500:])
```

Additionally, `_processed_update_ids_global` is a **class-level set** (line 169) shared across instances to survive restarts:

```python
# Line 168
_processed_update_ids_global: set[int] = set()
# Line 180
self._processed_update_ids = TelegramBot._processed_update_ids_global
```

### Layer 2: Message-level dedup via `_recent_message_ids` (lines ~1079–1092)

Inside `_handle_message()`, after extracting `(chat_id, message_id)`:

```python
# Lines 1069-1092
# Message-level dedup: Telegram guarantees at-least-once delivery.
# Even with update_id dedup, a restart can cause the same message
# to arrive under a different update_id. Use (chat_id, message_id)
# as a second dedup layer shared across all instances.
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

**Tracked fields:** `(chat_id, message_id)` tuples. This is also class-level (line 170):

```python
# Line 170
_recent_message_ids: set[tuple[int, int]] = set()
```

### Layer 3: Text-level dedup within `_handle_user_message()` (lines ~1214–1230)

Inside `_handle_user_message()` — prevents the same text from being processed twice within a 5-second window:

```python
# Lines 1214-1230
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

**Tracked fields:** `(chat_id, text)` tuples with timestamp. 5-second window, pruned to entries < 30s old.

### Layer 4: Tracked message dedup for `/clear` (lines ~215–237)

When tracking messages for `/clear` deletion, duplicate message IDs are skipped:

```python
# Line 231
if message_id not in cls._chat_message_ids[chat_id]:
    cls._chat_message_ids[chat_id].append(message_id)
```

And when `/clear` processes them:

```python
seen: set[int] = set()
message_ids = [mid for mid in raw_ids if not (mid in seen or seen.add(mid))]
```

### Summary of dedup fields

| Layer | Field(s) | Scope | Window | Location |
|-------|----------|-------|--------|----------|
| Update ID | `update_id` | Class-level global set | Last 500 IDs saved | `start()` loop |
| Chat+Message | `(chat_id, message_id)` | Class-level global set | Last 2500 tuples | `_handle_message()` |
| Chat+Text | `(chat_id, text)` | Instance-level dict | 5s window, pruned at 30s | `_handle_user_message()` |
| Tracked Msg IDs | `message_id` per chat | Per-chat list on disk | Last 1000 per chat | `_track_message()` |

---

## 3. STREAMING LOGIC

### Architecture

Streaming uses three methods on `TelegramBot` plus a background coroutine:

1. `start_streaming_task()` — initializes buffer
2. `append_streaming_text()` — appends text to buffer (called externally, e.g., by dispatcher)
3. `finalize_streaming_task()` — marks task as done
4. `_stream_editor_loop()` — background coroutine that periodically edits the Telegram message

### Initialization — `start_streaming_task()` (lines ~536–542)

```python
def start_streaming_task(self, task_id: str, chat_id: int, message_id: int) -> None:
    """Initialize streaming state for a task."""
    self._streaming_buffers[task_id] = ""
    self._streaming_meta[task_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "last_len": 0,
        "is_done": False,
    }
```

**Storage:** Two instance dicts:
- `_streaming_buffers: dict[str, str]` (line 191) — maps task_id → accumulated text
- `_streaming_meta: dict[str, dict]` (line 192) — maps task_id → metadata dict

### Appending — `append_streaming_text()` (lines ~544–551)

```python
def append_streaming_text(self, task_id: str, text: str) -> None:
    """Append text to the streaming buffer for a task."""
    if task_id in self._streaming_buffers:
        self._streaming_buffers[task_id] += text
```

### Finalization — `finalize_streaming_task()` (lines ~553–556)

```python
def finalize_streaming_task(self, task_id: str) -> None:
    """Mark a streaming task as done so the editor loop exits."""
    if task_id in self._streaming_meta:
        self._streaming_meta[task_id]["is_done"] = True
```

### Editor loop — `_stream_editor_loop()` (lines ~558–654)

**Edit interval:** 1.5 seconds (`await asyncio.sleep(1.5)` at line 570).

```python
async def _stream_editor_loop(self, task_id: str) -> str | None:
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
        if len(current_text) > meta["last_len"] + 5:
            # Truncate for Telegram limit during streaming
            if len(current_text) > 3900:
                display = current_text[:3900] + "\n\n<i>... (generating)</i>"
            else:
                display = current_text + "\n\n<i>⏳ Generating...</i>"
            try:
                success = await self._edit_message(chat_id, message_id, display)
                if success:
                    meta["last_len"] = len(current_text)
            except Exception as exc:
                logger.warning("stream edit failed for task {}: {}", task_id[:8], exc)
```

**Rate limiting for edits:** The `_edit_message()` method (lines ~465–531) calls `self._rate_limiter.wait_if_needed(chat_id)` which enforces the `RATE_LIMIT_PER_CHAT = 1.0` minimum interval. However, the rate limiter **only applies to sendMessage and editMessageText** — combined with the 1.5s edit interval, this means edits are naturally spaced at least 1.5s apart.

**Short-text optimization** (lines ~629–640):

```python
# Short-text optimization: if the final text is short (<100 chars),
# skip the streaming edits entirely and just edit once at the end.
final_text = self._streaming_buffers.get(task_id, "")
if len(final_text) < 100 and meta["last_len"] == 0:
    display = final_text
    try:
        await self._edit_message(chat_id, message_id, display)
    except Exception:
        pass
```

**Cleanup** (lines ~642–653):

```python
final_text = self._streaming_buffers.pop(task_id, "")
self._streaming_meta.pop(task_id, None)
return final_text
```

### How streaming is triggered (lines ~1262–1270 in `_handle_user_message()`)

```python
# Start streaming — initialize buffer and spawn background editor
if ack_msg_id is not None:
    self.start_streaming_task(task_id, chat_id, ack_msg_id)
    stream_task = asyncio.create_task(self._stream_editor_loop(task_id))
```

### How text is fed into the buffer

The buffer is filled via `append_streaming_text()`. Looking at the dispatcher (this is called externally — the bot doesn't push to the buffer itself). The bot exposes these methods for the dispatcher or relay to call.

---

## 4. MEDIA/PHOTO HANDLING

### Media detection in `_handle_message()` (lines ~1059–1066)

```python
# Check if message has media content
has_media = any(k in msg for k in ("photo", "document", "voice", "video", "audio", "sticker", "video_note", "animation"))

# Generate media description if present
media_desc = self._extract_media_info(msg) if has_media else ""

# If there's media but no text, use the media description as the text
if has_media and not text:
    text = media_desc
elif has_media and text and media_desc:
    text = f"📎 {media_desc}\n\n{text}"
```

### Media info extraction — `_extract_media_info()` (lines ~702–768)

Extracts metadata per media type:

```python
@staticmethod
def _extract_media_info(msg: dict) -> str:
    # Photo
    photos = msg.get("photo")
    if photos:
        largest = photos[-1]
        w, h = largest.get("width", 0), largest.get("height", 0)
        size = largest.get("file_size", 0)
        return f"📷 Photo ({w}x{h}, {_fmt_size(size)})"
    # Document: name + size
    # Voice: "🎤 Voice message"
    # Video: w, h, duration, size
    # Audio: duration, size, title/performer
    # Sticker: emoji + animated flag
    # Video note: "🎥 Video note (circular)"
    # Animation: "🎞️ GIF/Animation"
```

### File download logic (lines ~1156–1216 in `_handle_message()`)

```python
# Download media if present
media_file = None
media_type = None
media_filename = None

if has_media:
    file_id = None
    file_ext = ""

    if msg.get("photo"):
        photos = msg["photo"]
        file_id = photos[-1].get("file_id")      # <-- largest photo
        file_ext = ".jpg"
        media_type = "photo"
        media_filename = f"photo_{message_id}.jpg"

    elif msg.get("document"):
        doc = msg["document"]
        file_id = doc.get("file_id")
        media_type = "document"
        orig_name = doc.get("file_name", f"document_{message_id}")
        media_filename = orig_name
        # Determine extension from mime type if no file_name
        mime = doc.get("mime_type", "")
        if not doc.get("file_name"):
            media_filename = f"document_{message_id}"
            if "pdf" in mime: media_filename += ".pdf"
            elif "zip" in mime: media_filename += ".zip"
            elif "text" in mime: media_filename += ".txt"
    # ... (similar for voice, video, audio, sticker, video_note, animation)

    if file_id:
        logger.info("Telegram bot: downloading {} media (file_id={})", media_type, file_id[:16])
        media_file = await self._download_file(file_id)
```

### File download implementation — `_download_file()` (lines ~358–397)

```python
async def _download_file(self, file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id using getFile + download."""
    url = TELEGRAM_API_BASE.format(token=self.token, method="getFile")
    params = {"file_id": file_id}
    # ... gets file_path from getFile response ...
    download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
    dl_resp = await self._client.get(download_url, timeout=httpx.Timeout(30.0))
    return dl_resp.content  # or None on failure
```

### Media passed downstream (lines ~1212, ~1240–1260)

After download, media is passed to `_handle_user_message()`:

```python
await self._handle_user_message(
    chat_id, text,
    reply_to_message_id=message_id,
    media_file=media_file,
    media_type=media_type,
    media_filename=media_filename,
)
```

Inside `_handle_user_message()`, media is saved to disk and its path is stored in the task metadata:

```python
# Lines ~1240-1260
if media_file is not None and media_filename is not None:
    media_path = settings.project_root / "data" / "telegram_media" / f"{task_id}_{media_filename}"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(media_file)
    metadata_parts["media_path"] = str(media_path)
    metadata_parts["media_type"] = media_type
    metadata_parts["media_filename"] = media_filename
metadata = json.dumps(metadata_parts) if metadata_parts else None
```

### Is there any vision/description step? **NO.**

There is **no** LLM vision step or automatic image description. The raw bytes of photos are downloaded and saved to disk, but **no automated description** (e.g., via GPT-4V) is generated. The photo file path is stored in metadata for the downstream agent (master) to use, but the bot itself does not process or describe images. This is a gap — photos arrive as raw files on disk with no textual description unless the agent explicitly reads and describes them.

### Sending media back (lines ~1290–1325)

The bot can send media back to the user if the result metadata contains `generate_media_path`:

```python
media_path_from_result = result_metadata.get("generate_media_path")
media_type_from_result = result_metadata.get("generate_media_type", "document")

if media_path_from_result:
    full_media_path = settings.project_root / media_path_from_result
    if full_media_path.exists():
        file_data = full_media_path.read_bytes()
        filename = full_media_path.name
        sent = await self.send_media(
            chat_id, media_type_from_result, file_data, filename,
            caption=final_text, reply_to_message_id=reply_to_message_id,
        )
```

---

## 5. BOT INITIALIZATION

### Constructor — `TelegramBot.__init__()` (lines ~174–195)

```python
def __init__(self, token: str) -> None:
    self.token = token
    self._offset: int = 0
    self._processed_update_ids: set[int] = TelegramBot._processed_update_ids_global
    self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    self._rate_limiter = RateLimiter()
    self._auth = Authenticator(settings.telegram_auth_pin, settings.telegram_whitelist)
    self._bot_username: str | None = None
    self._running = False
    self._shutdown_event = asyncio.Event()
    self._streaming_buffers: dict[str, str] = {}
    self._streaming_meta: dict[str, dict] = {}
    TelegramBot._load_tracked_messages()
```

Key components:
- **httpx.AsyncClient** — direct HTTP calls to Telegram API (no `python-telegram-bot` dependency)
- **RateLimiter** — per-chat rate limiting at 1 msg/second
- **Authenticator** — PIN-based auth with optional whitelist
- **Streaming state** — task_id → buffer/meta dicts
- **Tracked messages** — loaded from disk on init

### Startup sequence — `start()` (lines ~215–293)

```python
async def start(self) -> None:
    async with TelegramBot._instance_lock:
        old_instance = TelegramBot._active_instance
        if old_instance is not None and old_instance is not self:
            await old_instance.stop()
            # Wait up to 5s for old instance to stop
            for _ in range(50):
                if not old_instance._running:
                    break
                await asyncio.sleep(0.1)
        TelegramBot._active_instance = self
        self._running = True
        self._shutdown_event.clear()

    while self._running and not self._shutdown_event.is_set():
        try:
            updates = await self._get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
            # ... process updates ...
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await asyncio.sleep(RETRY_DELAY)
    await self._client.aclose()
```

Key features:
- **Class-level `_instance_lock`** prevents duplicate instances polling the same token
- **Old instance signaling** — signals prior instance to stop before starting
- **Long-polling** — 30-second timeout on getUpdates
- **Shutdown event** — enables clean exit via `asyncio.Event()`

### FastAPI Integration — in `app/backend/main.py` (lines ~1036–1043 of main.py)

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

The bot runs as an `asyncio.create_task()` within FastAPI's `lifespan` context manager. On shutdown:

```python
# (in main.py lifespan finally block)
if telegram_bot is not None:
    await telegram_bot.stop()
if telegram_task is not None:
    telegram_task.cancel()
    await telegram_task
```

### Global instance accessor (lines ~1826–1831)

```python
_telegram_bot_instance: "TelegramBot | None" = None

def set_telegram_bot_instance(bot: "TelegramBot") -> None:
    global _telegram_bot_instance
    _telegram_bot_instance = bot

def get_telegram_bot_instance() -> "TelegramBot | None":
    return _telegram_bot_instance
```

---

## 6. AGENT INTERFACE

### How messages reach the agent system

Messages are forwarded to the agent system via **SQLite `task_queue` table**. The bot creates a queued task that the `dispatcher.py` loop picks up and routes to Master.

### Task creation — in `_handle_user_message()` (lines ~1240–1260)

```python
# Create task in queue
task_id = str(uuid.uuid4())
session_id = str(chat_id)
metadata_parts = {}
if reply_to_message_id is not None:
    metadata_parts["reply_to_message_id"] = reply_to_message_id
if media_file is not None and media_filename is not None:
    media_path = settings.project_root / "data" / "telegram_media" / f"{task_id}_{media_filename}"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(media_file)
    metadata_parts["media_path"] = str(media_path)
    metadata_parts["media_type"] = media_type
    metadata_parts["media_filename"] = media_filename
metadata = json.dumps(metadata_parts) if metadata_parts else None

create_queued_task(
    id=task_id,
    prompt=text,             # <-- THE USER'S TEXT IS THE PROMPT
    source="telegram",
    session_id=session_id,
    metadata=metadata,
)
```

### Message format going to the agent

The **`prompt` field** is exactly the user's text (possibly with media description prepended). For a photo with caption "what's this?", the prompt would be:

```
📎 📷 Photo (1920x1080, 340KB)

what's this?
```

For a forwarded message, a forward prefix is prepended in `_handle_message()` (line ~1105):

```text
📨 *Forwarded from user* @username (Name):

Actual message text here
```

No additional system instruction wrapper is added — the raw user text goes directly into the `prompt` field of the task_queue row.

### How results come back — `_wait_for_result()` (lines ~1340–1398)

```python
async def _wait_for_result(self, task_id: str, chat_id: int) -> tuple[str | None, dict | None]:
    start = datetime.now(timezone.utc).timestamp()
    last_typing = 0.0
    await self._send_chat_action(chat_id, action="typing")
    last_typing = start

    while True:
        elapsed = datetime.now(timezone.utc).timestamp() - start
        if elapsed >= TASK_TIMEOUT:  # 300 seconds
            return (None, None)

        task = get_queued_task(task_id)

        if task is None:
            await asyncio.sleep(TASK_POLL_INTERVAL)  # 1s
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
                    pass
            return (result, parsed_metadata)

        if status == "error":
            error_msg = task.get("error", "Unknown error")
            return (f"❌ An error occurred: {error_msg}", None)

        if status == "timeout":
            return (None, None)

        # Keep typing indicator alive
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts - last_typing >= 3.0:
            await self._send_chat_action(chat_id, action="typing")
            last_typing = now_ts

        await asyncio.sleep(TASK_POLL_INTERVAL)  # 1s
```

The bot **polls** the `task_queue` table every 1 second, waiting for Master to update the task status to `"done"` or `"error"`. The `result` field becomes the response text.

### Result delivery to user (lines ~1272–1335)

After `_wait_for_result()` returns:
1. If streaming was active, the stream editor is finalized and awaited
2. If result contains `generate_media_path`, media is sent via `send_media()` with the text as caption
3. For long responses (>4000 chars), text is split into chunks and sent as multiple messages
4. Otherwise, the ack message ("⏳ Processing...") is edited in-place with the final response
5. Fallback: a new message is sent if editing fails

### The dispatcher side (in `app/backend/dispatcher.py`)

The dispatcher loop reads `task_queue` rows with `source = "telegram"` (among others) and spawns the master agent. The master processes the prompt (raw user text) and writes its result back to the `task_queue` row's `result` field. The bot picks this up via polling.
