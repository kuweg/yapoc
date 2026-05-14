"""
Voice service — TTS and STT engines with offline-first fallback.
"""
import io
import logging
import tempfile
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class TTSEngine:
    """Text-to-Speech engine supporting offline (pyttsx3) and cloud (OpenAI, Google)."""

    def __init__(self):
        self._offline_engine = None
        self._offline_available = None

    def _get_offline_engine(self):
        if self._offline_available is None:
            try:
                import pyttsx3
                self._offline_engine = pyttsx3.init()
                self._offline_available = True
            except Exception as e:
                logger.debug(f"Offline TTS unavailable: {e}")
                self._offline_available = False
        return self._offline_engine if self._offline_available else None

    def synthesize(self, text: str, engine: str = "offline", voice: str = "",
                   speed: float = 1.0, fmt: str = "wav") -> bytes:
        """Synthesize speech and return audio bytes. Falls back through engine chain."""
        engines = [engine] if engine != "offline" else ["offline"]
        if "offline" not in engines:
            engines.append("offline")

        last_error = None
        for eng in engines:
            try:
                if eng == "offline":
                    return self._synthesize_offline(text, voice, speed, fmt)
                elif eng == "openai":
                    return self._synthesize_openai(text, voice, speed, fmt)
                elif eng == "google":
                    return self._synthesize_google(text, voice, speed, fmt)
            except Exception as e:
                logger.debug(f"TTS engine {eng} failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All TTS engines failed. Last error: {last_error}")

    def _synthesize_offline(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        engine = self._get_offline_engine()
        if engine is None:
            raise RuntimeError("Offline TTS engine (pyttsx3) not available")

        import pyttsx3

        if voice:
            try:
                engine.setProperty('voice', voice)
            except Exception:
                pass

        if speed != 1.0:
            try:
                rate = engine.getProperty('rate')
                engine.setProperty('rate', int(rate * speed))
            except Exception:
                pass

        # pyttsx3 doesn't directly output to bytes, so save to temp file
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            engine.save_to_file(text, str(tmp_path))
            engine.runAndWait()
            audio_bytes = tmp_path.read_bytes()
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

        return audio_bytes

    def _synthesize_openai(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        api_key = settings.openai_api_key
        if not api_key:
            raise RuntimeError("OpenAI API key not configured")

        import httpx

        model = getattr(settings, 'openai_tts_model', 'tts-1')
        tts_voice = voice or getattr(settings, 'openai_tts_voice', 'alloy')

        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "voice": tts_voice,
                "input": text,
                "speed": speed,
                "response_format": fmt,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.content

    def _synthesize_google(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        try:
            from google.cloud import texttospeech
        except ImportError:
            raise RuntimeError("google-cloud-texttospeech not installed")

        client = texttospeech.TextToSpeechClient()

        voice_name = voice or getattr(settings, 'google_tts_voice', 'en-US-Wavenet-D')
        language_code = "-".join(voice_name.split("-")[:2]) if "-" in voice_name else "en-US"

        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice_selection = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )

        encoding_map = {
            "wav": texttospeech.AudioEncoding.LINEAR16,
            "mp3": texttospeech.AudioEncoding.MP3,
            "ogg": texttospeech.AudioEncoding.OGG_OPUS,
        }
        audio_config = texttospeech.AudioConfig(
            audio_encoding=encoding_map.get(fmt, texttospeech.AudioEncoding.LINEAR16),
            speaking_rate=speed,
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_selection,
            audio_config=audio_config,
        )
        return response.audio_content

    def list_voices(self) -> dict[str, dict]:
        """Return available voices grouped by engine."""
        result: dict[str, dict] = {}

        # Offline voices
        offline = self._get_offline_engine()
        if offline:
            try:
                voices = offline.getProperty('voices')
                voice_list = []
                for v in voices:
                    langs = getattr(v, 'languages', [])
                    lang = langs[0].decode() if langs and isinstance(langs[0], bytes) else (langs[0] if langs else '')
                    voice_list.append({
                        "id": v.id,
                        "name": v.name,
                        "language": lang,
                        "gender": getattr(v, 'gender', '') or '',
                    })
                result["offline"] = {"available": True, "voices": voice_list or [{"id": "default", "name": "System Default", "language": "", "gender": ""}]}
            except Exception:
                result["offline"] = {"available": True, "voices": [{"id": "default", "name": "System Default", "language": "", "gender": ""}]}
        else:
            result["offline"] = {"available": False, "voices": []}

        # OpenAI voices (static list)
        result["openai"] = {
            "available": bool(settings.openai_api_key),
            "voices": [
                {"id": "alloy", "name": "Alloy", "language": "en-US", "gender": "neutral"},
                {"id": "echo", "name": "Echo", "language": "en-US", "gender": "male"},
                {"id": "fable", "name": "Fable", "language": "en-GB", "gender": "neutral"},
                {"id": "onyx", "name": "Onyx", "language": "en-US", "gender": "male"},
                {"id": "nova", "name": "Nova", "language": "en-US", "gender": "female"},
                {"id": "shimmer", "name": "Shimmer", "language": "en-US", "gender": "female"},
            ],
        }

        # Google voices
        result["google"] = {"available": False, "voices": []}
        try:
            from google.cloud import texttospeech
            result["google"]["available"] = True
        except ImportError:
            pass

        return result


class STTEngine:
    """Speech-to-Text engine supporting offline (Sphinx) and cloud (Whisper, Google)."""

    def __init__(self):
        self._offline_recognizer = None
        self._offline_available = None

    def _get_offline_recognizer(self):
        if self._offline_available is None:
            try:
                import speech_recognition as sr
                self._offline_recognizer = sr.Recognizer()
                self._offline_available = True
            except Exception as e:
                logger.debug(f"Offline STT unavailable: {e}")
                self._offline_available = False
        return self._offline_recognizer if self._offline_available else None

    def transcribe(self, audio_bytes: bytes, engine: str = "offline",
                   language: str = "en-US") -> dict:
        """Transcribe audio bytes and return {text, confidence, engine, duration_ms}."""
        engines = [engine] if engine != "offline" else ["sphinx"]
        if "sphinx" not in engines:
            engines.append("sphinx")

        last_error = None
        for eng in engines:
            try:
                if eng in ("sphinx", "offline"):
                    return self._transcribe_sphinx(audio_bytes)
                elif eng == "openai":
                    return self._transcribe_openai(audio_bytes, language)
                elif eng == "google":
                    return self._transcribe_google(audio_bytes, language)
            except Exception as e:
                logger.debug(f"STT engine {eng} failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All STT engines failed. Last error: {last_error}")

    def _transcribe_sphinx(self, audio_bytes: bytes) -> dict:
        import speech_recognition as sr

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        try:
            recognizer = self._get_offline_recognizer()
            if recognizer is None:
                raise RuntimeError("Offline STT engine not available")

            with sr.AudioFile(str(tmp_path)) as source:
                audio = recognizer.record(source)

            text = recognizer.recognize_sphinx(audio)
            return {"text": text, "confidence": 0.0, "engine": "sphinx", "duration_ms": 0}
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

    def _transcribe_openai(self, audio_bytes: bytes, language: str) -> dict:
        api_key = settings.openai_api_key
        if not api_key:
            raise RuntimeError("OpenAI API key not configured")

        import httpx

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        try:
            with open(tmp_path, "rb") as f:
                response = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": f},
                    data={"model": "whisper-1", "language": language},
                    timeout=60.0,
                )
            response.raise_for_status()
            data = response.json()
            return {
                "text": data.get("text", ""),
                "confidence": 0.0,
                "engine": "openai-whisper",
                "duration_ms": 0,
            }
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

    def _transcribe_google(self, audio_bytes: bytes, language: str) -> dict:
        try:
            from google.cloud import speech
        except ImportError:
            raise RuntimeError("google-cloud-speech not installed")

        client = speech.SpeechClient()

        audio = speech.RecognitionAudio(content=audio_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code=language,
        )

        response = client.recognize(config=config, audio=audio)
        text = ""
        confidence = 0.0
        for result in response.results:
            if result.alternatives:
                text += result.alternatives[0].transcript
                confidence = max(confidence, result.alternatives[0].confidence)

        return {"text": text, "confidence": confidence, "engine": "google", "duration_ms": 0}


# Singleton instances
_tts_engine: TTSEngine | None = None
_stt_engine: STTEngine | None = None


def get_tts_engine() -> TTSEngine:
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = TTSEngine()
    return _tts_engine


def get_stt_engine() -> STTEngine:
    global _stt_engine
    if _stt_engine is None:
        _stt_engine = STTEngine()
    return _stt_engine
