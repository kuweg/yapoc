"""Telegram tools for sending text messages and media files."""

from pathlib import Path
from typing import Any

from app.config import settings

from . import BaseTool


class SendTelegramMessageTool(BaseTool):
    name = "send_telegram_message"
    description = (
        "Send a message to the user via Telegram. Use this to notify the user "
        "of important events, task completions, errors, or anything the user "
        "needs to know. Only works if Telegram bot is configured."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The text message to send via Telegram",
            },
            "reply_to_message_id": {
                "type": "integer",
                "description": "Optional message ID to reply to",
            },
        },
        "required": ["message"],
    }

    async def execute(self, **params: Any) -> str:
        message = params.get("message", "").strip()
        if not message:
            return "ERROR: send_telegram_message failed — message is required"

        try:
            from app.backend.telegram_bot import get_telegram_bot_instance

            bot = get_telegram_bot_instance()
            if bot is None:
                return "ERROR: Telegram bot is not configured or not running"

            # Find an authorized chat to send to
            # Check both authenticated chats AND whitelisted chats
            authorized_chats = bot._auth._authorized_chats
            whitelist = bot._auth._whitelist
            all_authorized = authorized_chats | whitelist
            if not all_authorized:
                return "ERROR: No authorized Telegram chats found — user has not authenticated"

            # Send to the first authorized chat (prefer authenticated over whitelisted)
            chat_id = next(iter(all_authorized))
            reply_to = params.get("reply_to_message_id")

            # Auto-split long messages (Telegram hard limit is 4096 chars)
            chunks = bot._split_text_for_telegram(message, max_len=4000)
            sent_ids = []
            for i, chunk in enumerate(chunks):
                # Only apply reply_to on the first chunk
                chunk_reply_to = reply_to if i == 0 else None
                msg_id = await bot._send_message(chat_id, chunk, reply_to_message_id=chunk_reply_to)
                if msg_id is not None:
                    sent_ids.append(msg_id)

            if sent_ids:
                if len(sent_ids) == 1:
                    return f"✅ Telegram message sent to chat {chat_id} (message_id: {sent_ids[0]})"
                else:
                    return f"✅ Telegram message sent to chat {chat_id} in {len(sent_ids)} parts (message_ids: {sent_ids})"
            else:
                return f"ERROR: Failed to send Telegram message to chat {chat_id}"
        except Exception as exc:
            return f"ERROR: send_telegram_message failed — {exc}"


class SendTelegramMediaTool(BaseTool):
    name = "send_telegram_media"
    description = (
        "Send an image or document file to the user via Telegram. Use this to send "
        "generated plot/chart images, screenshots, or any file. Accepts a "
        "project-root-relative file path (or absolute path under project root). "
        "Only works if the Telegram bot is configured."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Project-root-relative path to the file to send, e.g. data/generated/foo.png",
            },
            "caption": {
                "type": "string",
                "description": "Optional caption for the Telegram media",
            },
            "media_type": {
                "type": "string",
                "enum": ["photo", "document"],
                "default": "photo",
                "description": "Telegram media type; defaults to photo",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> str:
        raw_path = params.get("path", "")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return "ERROR: send_telegram_media failed — path is required"

        try:
            project_root = settings.project_root.resolve()
            candidate = Path(raw_path).expanduser()
            file_path = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
            try:
                file_path.relative_to(project_root)
            except ValueError:
                return f"ERROR: file path must be under project root: {raw_path}"

            if not file_path.is_file():
                return f"ERROR: file not found: {raw_path}"

            file_bytes = file_path.read_bytes()
            filename = file_path.name
            media_type = params.get("media_type", "photo")
            if media_type not in {"photo", "document"}:
                return "ERROR: send_telegram_media failed — media_type must be photo or document"
            caption = params.get("caption")

            from app.backend.telegram_bot import get_telegram_bot_instance

            bot = get_telegram_bot_instance()
            if bot is None:
                return "ERROR: Telegram bot is not configured or not running"

            all_authorized = bot._auth._authorized_chats | bot._auth._whitelist
            if not all_authorized:
                return "ERROR: No authorized Telegram chats found"

            chat_id = next(iter(all_authorized))
            msg_id = await bot.send_media(chat_id, media_type, file_bytes, filename, caption=caption)
            if msg_id is None:
                return "ERROR: Failed to send Telegram media"
            return f"✅ Telegram {media_type} sent to chat {chat_id} (message_id: {msg_id})"
        except Exception as exc:
            return f"ERROR: send_telegram_media failed — {exc}"


class SendTelegramVoiceTool(BaseTool):
    name = "send_telegram_voice"
    description = (
        "Synthesize text into a spoken voice message (OpenAI onyx TTS) and send it "
        "proactively to the user via Telegram as a voice note. Use this to speak to "
        "the user on your own initiative — e.g. announce task completion, alerts, or "
        "anything the user should hear. Only works if the Telegram bot is configured."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to speak",
            },
            "voice": {
                "type": "string",
                "description": "TTS voice; defaults to settings.openai_tts_voice or 'onyx'",
            },
            "speed": {
                "type": "number",
                "default": 1.0,
                "description": "Speech speed",
            },
            "reply_to_message_id": {
                "type": "integer",
                "description": "Optional message ID to reply to",
            },
        },
        "required": ["text"],
    }

    async def execute(self, **params: Any) -> str:
        text = params.get("text", "").strip()
        if not text:
            return "ERROR: send_telegram_voice failed — text is required"

        try:
            from app.backend.telegram_bot import get_telegram_bot_instance

            bot = get_telegram_bot_instance()
            if bot is None:
                return "ERROR: Telegram bot is not configured or not running"

            all_authorized = bot._auth._authorized_chats | bot._auth._whitelist
            if not all_authorized:
                return "ERROR: No authorized Telegram chats found — user has not authenticated"

            chat_id = next(iter(all_authorized))
            reply_to = params.get("reply_to_message_id")

            from app.backend.services.voice_service import get_tts_engine

            tts = get_tts_engine()
            voice = params.get("voice") or settings.openai_tts_voice or "onyx"
            speed = float(params.get("speed", 1.0))
            # Use mp3 + sendAudio (not opus + sendVoice): Telegram voice notes
            # (sendVoice) are rejected with VOICE_MESSAGES_FORBIDDEN for this bot,
            # while audio files (sendAudio) are delivered reliably.
            audio = tts.synthesize(text=text, engine="openai", voice=voice, speed=speed, fmt="mp3")

            if not audio:
                return "ERROR: TTS returned empty audio"

            msg_id = await bot.send_media(chat_id, "audio", audio, "voice.mp3", caption=None, reply_to_message_id=reply_to)
            if msg_id is None:
                return "ERROR: Failed to send Telegram voice message"
            return f"✅ Telegram voice message sent to chat {chat_id} (message_id: {msg_id})"
        except Exception as exc:
            return f"ERROR: send_telegram_voice failed — {exc}"
