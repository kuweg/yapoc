from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.utils.tools.telegram import SendTelegramMediaTool


class FakeTelegramBot:
    def __init__(self) -> None:
        self._auth = SimpleNamespace(_authorized_chats={111}, _whitelist=set())
        self.calls: list[dict] = []

    async def send_media(self, chat_id, media_type, file_data, filename, caption=None):
        self.calls.append(
            {
                "chat_id": chat_id,
                "media_type": media_type,
                "file_data": file_data,
                "filename": filename,
                "caption": caption,
            }
        )
        return 12345


@pytest.mark.asyncio
async def test_send_telegram_media_sends_project_file(monkeypatch):
    from app.backend import telegram_bot

    fake_bot = FakeTelegramBot()
    monkeypatch.setattr(telegram_bot, "get_telegram_bot_instance", lambda: fake_bot)

    file_path = settings.project_root / "data" / "generated" / "test_plot.png"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        result = await SendTelegramMediaTool().execute(
            path="data/generated/test_plot.png", caption="hi"
        )
    finally:
        file_path.unlink(missing_ok=True)

    assert "12345" in result
    assert fake_bot.calls[0]["media_type"] == "photo"
    assert fake_bot.calls[0]["caption"] == "hi"


@pytest.mark.asyncio
async def test_send_telegram_media_missing_file_returns_error():
    result = await SendTelegramMediaTool().execute(
        path="data/generated/does-not-exist.png"
    )

    assert result.startswith("ERROR")
