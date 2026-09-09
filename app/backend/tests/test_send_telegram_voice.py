import pytest
from types import SimpleNamespace

from app.utils.tools.telegram import SendTelegramVoiceTool


@pytest.mark.asyncio
async def test_send_telegram_voice_synthesizes_and_sends(monkeypatch):
    class FakeTelegramBot:
        def __init__(self):
            self._auth = SimpleNamespace(_authorized_chats={111}, _whitelist=set())
            self.calls = []

        async def send_media(
            self,
            chat_id,
            media_type,
            file_data,
            filename,
            caption=None,
            reply_to_message_id=None,
        ):
            self.calls.append(
                {
                    "chat_id": chat_id,
                    "media_type": media_type,
                    "file_data": file_data,
                    "filename": filename,
                    "caption": caption,
                    "reply_to_message_id": reply_to_message_id,
                }
            )
            return 12345

    class FakeTTSEngine:
        def synthesize(self, *args, **kwargs):
            return b"FAKE_OPUS_AUDIO"

    fake_bot = FakeTelegramBot()

    monkeypatch.setattr(
        "app.backend.telegram_bot.get_telegram_bot_instance",
        lambda: fake_bot,
    )
    monkeypatch.setattr(
        "app.backend.services.voice_service.get_tts_engine",
        lambda: FakeTTSEngine(),
    )

    result = await SendTelegramVoiceTool().execute(text="Hello world")

    assert "12345" in result
    assert fake_bot.calls[0]["media_type"] == "audio"
    assert fake_bot.calls[0]["file_data"] == b"FAKE_OPUS_AUDIO"
    assert fake_bot.calls[0]["filename"] == "voice.mp3"


@pytest.mark.asyncio
async def test_send_telegram_voice_empty_text_returns_error():
    result = await SendTelegramVoiceTool().execute(text="   ")
    assert result.startswith("ERROR")
