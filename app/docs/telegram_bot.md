# Telegram Bot Integration

YAPOC can be accessed via Telegram. This allows you to chat with the Master agent from your phone.

## Setup

### 1. Create a Bot with BotFather

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Save the API token you receive (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Configure YAPOC

Add the token to your `.env` file:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

### 3. Restart YAPOC

```bash
yapoc restart
# or restart your uvicorn server
```

You should see in the logs: `Telegram bot started (polling mode)`

### 4. Start Chatting

1. Open Telegram and find your bot
2. Send `/start` to see the welcome message
3. Send any message to chat with Master

## How It Works

1. Your message is sent to YAPOC's task queue with `source="telegram"`
2. The task dispatcher picks it up and routes it to the Master agent
3. Master processes it and writes the result
4. The bot polls for completion and sends the response back to you

## Commands

- `/start` — Welcome message and instructions
- `/help` — Show available commands
- Any other message — Forwarded to Master for processing

## Limitations

- Responses may take a few seconds depending on Master's workload
- Only private chats are supported (not group chats)
- Rate limited to 1 message per second per chat
