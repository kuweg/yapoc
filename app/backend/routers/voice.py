"""
Voice API endpoints — TTS synthesis and STT transcription.
"""
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.backend.models.voice import TTSRequest, STTResponse, TTSVoicesResponse
from app.backend.services.voice_service import get_tts_engine, get_stt_engine
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])


@router.get("/tts/voices", response_model=TTSVoicesResponse)
async def list_voices():
    """List available TTS voices across all engines."""
    if not settings.voice_enabled:
        raise HTTPException(status_code=503, detail="Voice feature is disabled")
    engine = get_tts_engine()
    voices = engine.list_voices()
    return TTSVoicesResponse(engines=voices)


@router.post("/tts")
async def synthesize_speech(req: TTSRequest):
    """Synthesize speech from text and return audio bytes."""
    if not settings.voice_enabled:
        raise HTTPException(status_code=503, detail="Voice feature is disabled")

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    try:
        engine = get_tts_engine()
        audio_bytes = engine.synthesize(
            text=req.text,
            engine=req.engine,
            voice=req.voice,
            speed=req.speed,
            fmt=req.fmt,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    content_type_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
    }
    content_type = content_type_map.get(req.fmt, "audio/wav")

    return Response(content=audio_bytes, media_type=content_type)


@router.post("/stt", response_model=STTResponse)
async def transcribe_speech(
    audio: UploadFile = File(...),
    engine: str = Form(default="offline"),
    language: str = Form(default="en-US"),
):
    """Transcribe uploaded audio to text."""
    if not settings.voice_enabled:
        raise HTTPException(status_code=503, detail="Voice feature is disabled")

    if not audio.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")

    try:
        audio_bytes = await audio.read()
        stt_engine = get_stt_engine()
        result = stt_engine.transcribe(
            audio_bytes=audio_bytes,
            engine=engine,
            language=language,
        )
        return STTResponse(
            text=result["text"],
            confidence=result["confidence"],
            engine=result["engine"],
            duration_ms=result["duration_ms"],
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"STT transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
