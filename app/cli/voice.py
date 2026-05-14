"""
Voice module for YAPOC CLI — Text-to-Speech and Speech-to-Text.
Offline-first with optional cloud fallback.
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class TextToSpeech:
    """Offline TTS engine using pyttsx3 (espeak/SAPI5/NSSpeechSynthesizer)."""

    def __init__(self):
        self._engine = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._available = True
        except Exception as e:
            logger.debug(f"TTS engine unavailable: {e}")
            self._available = False
        return self._available

    def speak(self, text: str) -> bool:
        if not text.strip():
            return False
        if not self.is_available():
            logger.warning("TTS engine not available")
            return False
        try:
            self._engine.say(text)
            self._engine.runAndWait()
            return True
        except Exception as e:
            logger.error(f"TTS speak failed: {e}")
            return False

    def set_rate(self, rate: int):
        """Set speech rate in words per minute."""
        if self.is_available():
            try:
                self._engine.setProperty('rate', rate)
            except Exception as e:
                logger.debug(f"Failed to set TTS rate: {e}")

    def list_voices(self) -> list[dict]:
        if not self.is_available():
            return [{"id": "default", "name": "System Default", "language": "", "gender": ""}]
        try:
            voices = self._engine.getProperty('voices')
            result = []
            for v in voices:
                langs = getattr(v, 'languages', [])
                lang = langs[0].decode() if langs and isinstance(langs[0], bytes) else (langs[0] if langs else '')
                result.append({
                    "id": v.id,
                    "name": v.name,
                    "language": lang,
                    "gender": getattr(v, 'gender', '') or '',
                })
            return result if result else [{"id": "default", "name": "System Default", "language": "", "gender": ""}]
        except Exception:
            return [{"id": "default", "name": "System Default", "language": "", "gender": ""}]

    def cleanup(self):
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass
            self._engine = None
            self._available = None


class SpeechToText:
    """Offline STT using CMU Sphinx with optional cloud fallback."""

    def __init__(self):
        self._recognizer = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._available = True
        except Exception as e:
            logger.debug(f"STT engine unavailable: {e}")
            self._available = False
        return self._available

    def listen(self, timeout: float | None = None, phrase_limit: float | None = None) -> str:
        if not self.is_available():
            logger.warning("STT engine not available")
            return ""

        import speech_recognition as sr

        if timeout is None:
            timeout = getattr(settings, 'stt_timeout', 5.0)
        if phrase_limit is None:
            phrase_limit = getattr(settings, 'stt_phrase_limit', 10.0)

        engine = getattr(settings, 'stt_engine', 'sphinx')
        language = getattr(settings, 'stt_language', 'en-US')

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        except sr.WaitTimeoutError:
            logger.debug("STT: no speech detected (timeout)")
            return ""
        except Exception as e:
            logger.error(f"Microphone error: {e}")
            return ""

        engines = [engine] if engine != "offline" else ["sphinx"]
        if "sphinx" not in engines:
            engines.append("sphinx")

        for eng in engines:
            try:
                if eng == "sphinx":
                    return self._recognizer.recognize_sphinx(audio)
                elif eng == "google":
                    return self._recognizer.recognize_google(audio, language=language)
                elif eng == "openai":
                    api_key = settings.openai_api_key
                    if not api_key:
                        continue
                    return self._recognizer.recognize_whisper_api(audio, api_key=api_key)
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                logger.debug(f"STT engine {eng} request error: {e}")
                continue
            except Exception as e:
                logger.debug(f"STT engine {eng} error: {e}")
                continue

        return ""

    def cleanup(self):
        self._recognizer = None
        self._available = None


# Singleton instances
_tts: TextToSpeech | None = None
_stt: SpeechToText | None = None


def get_tts() -> TextToSpeech:
    global _tts
    if _tts is None:
        _tts = TextToSpeech()
    return _tts


def get_stt() -> SpeechToText:
    global _stt
    if _stt is None:
        _stt = SpeechToText()
    return _stt


def cleanup_voice():
    global _tts, _stt
    if _tts:
        _tts.cleanup()
        _tts = None
    if _stt:
        _stt.cleanup()
        _stt = None
