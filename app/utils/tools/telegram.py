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
            authorized_chats = bot._auth._authorized_chats
            if not authorized_chats:
                return "ERROR: No authorized Telegram chats found — user has not authenticated"

            # Send to the first authorized chat
            chat_id = next(iter(authorized_chats))
            msg_id = await bot._send_message(chat_id, message)
            if msg_id is not None:
                return f"✅ Telegram message sent to chat {chat_id} (message_id: {msg_id})"
            else:
                return f"ERROR: Failed to send Telegram message to chat {chat_id}"
        except Exception as exc:
            return f"ERROR: send_telegram_message failed — {exc}"
