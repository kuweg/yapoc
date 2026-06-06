"""SendTelegramMessageTool — allows agents to send messages via Telegram."""

from typing import Any

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
