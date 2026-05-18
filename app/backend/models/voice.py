from pydantic import BaseModel, Field
from typing import Literal


class TTSRequest(BaseModel):
    text: str = Field(..., max_length=4096, description="Text to synthesize")
    # ``None`` (omitted) → server resolves from ``settings.tts_engine``.
    # Without this indirection the model default would override the global
    # configured default — the route handler now reads `req.engine or
    # settings.tts_engine`, making settings the single source of truth.
    engine: Literal["offline", "openai", "google"] | None = None
    voice: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    fmt: Literal["wav", "mp3", "ogg"] = Field(default="wav", alias="format")
    stream: bool = False


class TTSVoice(BaseModel):
    id: str
    name: str
    language: str
    gender: str


class TTSVoicesResponse(BaseModel):
    engines: dict[str, dict]


class STTRequest(BaseModel):
    # Same indirection as TTSRequest — defer to ``settings.stt_engine`` when
    # the caller omits the field.
    engine: Literal["offline", "openai", "google"] | None = None
    language: str = "en-US"


class STTResponse(BaseModel):
    text: str
    confidence: float = 0.0
    engine: str
    duration_ms: int = 0
