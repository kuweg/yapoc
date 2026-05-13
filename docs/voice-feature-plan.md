# Voice Feature Design Plan — YAPOC

> **Status:** Planning Document  
> **Date:** 2026-05-13  
> **Philosophy:** Offline-first, cloud fallback, both CLI and UI modes, bidirectional (TTS + STT)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Dependencies](#2-dependencies)
3. [Implementation Phases](#3-implementation-phases)
4. [File-by-File Changes](#4-file-by-file-changes)
5. [Trade-offs](#5-trade-offs)
6. [API Design](#6-api-design)

---

## 1. Architecture Overview

### 1.1 Current Architecture (Baseline)

YAPOC has three interaction surfaces:

| Surface | Technology | Communication |
|---------|-----------|---------------|
| **CLI** | Typer + Rich + prompt_toolkit | HTTP POST `/api/task/stream` (SSE) |
| **UI** (React SPA) | Vite + React + Zustand | HTTP POST `/api/task/stream` (SSE) + WebSocket `/ws` |
| **Backend** | FastAPI + uvicorn | REST + WebSocket + SSE |

The backend runs as a single uvicorn process. The frontend is served as a static SPA (Vite build in `app/frontend/dist/`). The CLI connects to the backend via HTTP.

### 1.2 Voice Architecture — High Level

Voice adds two new data flows:

```
User ──[mic]──> STT ──> text ──> YAPOC Backend ──> text ──> TTS ──[speaker]──> User
```

**Two modes, two integration strategies:**

#### CLI Mode (offline-first)
- **TTS (system → user):** `pyttsx3` reads assistant responses aloud via local TTS engine (espeak on Linux, SAPI5 on Windows, NSSpeechSynthesizer on macOS).
- **STT (user → system):** `speech_recognition` captures microphone input and transcribes via offline `recognize_sphinx` (CMU Sphinx) or cloud fallback `recognize_google` / `recognize_whisper_api`.
- Voice is triggered by slash commands: `/voice` enters voice mode, `/speak` reads last response, `/listen` captures mic input.

#### UI Mode (browser-native)
- **TTS (system → user):** Backend returns audio bytes via a new REST endpoint. Frontend uses the **Web Audio API** (`AudioContext` + `AudioBuffer`) to play them. Alternatively, the frontend can use the **Web Speech API** (`SpeechSynthesisUtterance`) for client-side TTS with no backend round-trip.
- **STT (user → system):** Frontend uses the **Web Speech API** (`SpeechRecognition`) for in-browser speech-to-text. No backend involvement for the recognition itself — the transcribed text is sent as a normal chat message.
- A "mic" button in the ChatPanel input area toggles listening mode.

### 1.3 Data Flow Diagrams

#### Flow A: CLI TTS (system speaks to user)

```
Backend (text response)
    │
    ▼
CLI receives SSE stream → accumulates full response text
    │
    ▼
User types /speak or voice mode is active
    │
    ▼
pyttsx3.init() → engine.say(text) → engine.runAndWait()
    │
    ▼
Audio plays through system speakers
```

#### Flow B: CLI STT (user speaks to system)

```
User speaks into microphone
    │
    ▼
speech_recognition.Microphone() → recognizer.listen(source)
    │
    ▼
recognizer.recognize_sphinx(audio)  [offline]
  OR recognizer.recognize_google(audio)  [cloud fallback]
    │
    ▼
Transcribed text → injected as CLI input → sent to backend as normal message
```

#### Flow C: UI TTS (browser plays audio from backend)

```
Backend generates text response (SSE stream)
    │
    ▼
Frontend accumulates text → calls POST /api/tts with text
    │
    ▼
Backend TTS engine (pyttsx3 or OpenAI TTS) → returns WAV/MP3 bytes
    │
    ▼
Frontend: AudioContext.decodeAudioData() → audioBuffer → source.start()
    │
    ▼
Audio plays through browser
```

#### Flow D: UI TTS (browser-native, no backend)

```
Backend generates text response (SSE stream)
    │
    ▼
Frontend accumulates text
    │
    ▼
Frontend: new SpeechSynthesisUtterance(text) → speechSynthesis.speak(utterance)
    │
    ▼
Browser's built-in TTS engine speaks (no backend call)
```

#### Flow E: UI STT (browser-native)

```
User clicks mic button in ChatPanel
    │
    ▼
Frontend: new SpeechRecognition() → recognition.start()
    │
    ▼
Browser captures mic → onresult callback → transcript text
    │
    ▼
Transcript injected into chat input → user sends as normal message
```

### 1.4 Both Directions Summary

| Direction | CLI Mode | UI Mode |
|-----------|----------|---------|
| **System → User (TTS)** | pyttsx3 (offline) | Web Speech API (browser-native) or backend TTS endpoint |
| **User → System (STT)** | speech_recognition + Sphinx (offline) | Web Speech API (browser-native) |

---

## 2. Dependencies

### 2.1 Python Packages (pyproject.toml)

#### Core (offline-first — always installed)

```toml
# Text-to-Speech (offline)
"pyttsx3>=2.90"           # Cross-platform TTS via system engines (espeak, SAPI5, NSSpeechSynthesizer)

# Speech-to-Text (offline)
"SpeechRecognition>=3.10.0"  # Microphone capture + multiple recognition backends
"pyaudio>=0.2.14"            # PortAudio bindings for microphone access (system dep: portaudio)
```

#### Cloud Fallback (optional — installed on demand or gated by config)

```toml
# OpenAI TTS/STT (cloud)
"openai>=1.0.0"            # Already may be present for LLM; adds TTS + STT endpoints

# Google Cloud Speech (cloud)
"google-cloud-speech>=2.0.0"  # Google STT (higher quality than Web Speech API)
"google-cloud-texttospeech>=2.0.0"  # Google TTS (WaveNet voices)
```

### 2.2 System-Level Dependencies

| Package | Purpose | Install (Ubuntu/Debian) |
|---------|---------|------------------------|
| `portaudio19-dev` | Microphone capture (pyaudio) | `sudo apt install portaudio19-dev` |
| `espeak` / `espeak-ng` | Offline TTS engine (pyttsx3 on Linux) | `sudo apt install espeak espeak-ng` |
| `libespeak-dev` | espeak dev headers | `sudo apt install libespeak-dev` |
| `ffmpeg` | Audio format conversion (optional) | `sudo apt install ffmpeg` |
| `python3-pyaudio` | System pyaudio (fallback) | `sudo apt install python3-pyaudio` |

**macOS:** `brew install portaudio espeak`  
**Windows:** No system deps — SAPI5 and pywin32 are built-in.

### 2.3 Frontend Dependencies

**None.** The Web Speech API (`SpeechRecognition` + `SpeechSynthesis`) is built into all modern browsers (Chrome, Edge, Safari, Firefox). No npm packages needed.

---

## 3. Implementation Phases

### Phase 1: MVP — CLI TTS Only

**Goal:** System speaks responses aloud in CLI mode.

**Scope:**
- Add `pyttsx3` to `pyproject.toml`
- Create `app/cli/voice.py` with a `TextToSpeech` class wrapping pyttsx3
- Add `/speak` slash command to CLI REPL (`app/cli/main.py`)
- Add `--voice` flag to `yapoc chat` command to auto-speak every response
- Handle engine initialization, error fallback (silent if no engine available)

**Success criteria:** User types `/speak` and hears the last assistant response.

### Phase 2: CLI STT

**Goal:** User speaks into microphone and text appears as input.

**Scope:**
- Add `SpeechRecognition` + `pyaudio` to `pyproject.toml`
- Extend `app/cli/voice.py` with a `SpeechToText` class
- Add `/listen` slash command — captures mic, transcribes, fills input buffer
- Add `/voice` toggle — continuous voice mode (listen → transcribe → send → listen again)
- Offline default: CMU Sphinx (`recognize_sphinx`). Cloud fallback: Google Web Speech API (`recognize_google`) or OpenAI Whisper (`recognize_whisper_api`)

**Success criteria:** User types `/listen`, speaks "list agents", and the CLI sends "list agents" as a message.

### Phase 3: Backend TTS/STT API Endpoints

**Goal:** Backend can synthesize speech and transcribe audio via REST.

**Scope:**
- Create `app/backend/routers/voice.py` with:
  - `POST /api/tts` — accepts text, returns audio bytes (WAV/MP3)
  - `POST /api/stt` — accepts audio upload, returns transcribed text
  - `GET /api/tts/voices` — lists available voices
- Create `app/backend/services/voice_service.py` with:
  - `TTSEngine` class: offline (pyttsx3) + cloud (OpenAI TTS, Google TTS) with fallback
  - `STTEngine` class: offline (Sphinx) + cloud (OpenAI Whisper, Google STT) with fallback
- Register router in `app/backend/main.py`
- Add config settings for voice engine selection, voice ID, speed, language

**Success criteria:** `curl -X POST /api/tts -d '{"text":"Hello"}'` returns audio bytes.

### Phase 4: UI Integration

**Goal:** Voice works in the browser UI.

**Scope:**
- **STT:** Add mic button to `ChatPanel.tsx` — uses Web Speech API `SpeechRecognition`
  - On click: starts listening, shows pulsing mic icon
  - On result: fills input textarea with transcript
  - On end: auto-sends or waits for user to press Enter
- **TTS (browser-native):** Add speaker button to each assistant message bubble
  - Uses `SpeechSynthesisUtterance` — no backend call needed
  - Respects browser voice selection
- **TTS (backend-mediated):** Add "Play as audio" option
  - Calls `POST /api/tts` with the message text
  - Plays returned audio via `AudioContext`
- Add voice settings panel (toggle auto-speak, select voice, adjust speed)

**Success criteria:** User clicks mic, speaks, and text appears in chat input. Assistant messages have a speaker icon that reads them aloud.

### Phase 5: Cloud Fallback & Quality Improvements

**Goal:** High-quality voice when internet is available.

**Scope:**
- Add OpenAI TTS integration (`tts-1` or `tts-1-hd` models) to `TTSEngine`
- Add OpenAI Whisper integration (`whisper-1`) to `STTEngine`
- Add Google Cloud Text-to-Speech (WaveNet voices) to `TTSEngine`
- Add Google Cloud Speech-to-Text to `STTEngine`
- Implement automatic fallback chain: cloud → offline → error
- Add voice activity detection (VAD) for better STT segmentation
- Add audio streaming for TTS (chunked responses instead of waiting for full synthesis)
- Add language detection / multi-language support
- Add voice customization (speed, pitch, volume controls)

**Success criteria:** Cloud voices are used when API keys are present; seamless fallback to offline when not.

---

## 4. File-by-File Changes

### Phase 1: CLI TTS

| File | Action | Changes |
|------|--------|---------|
| `pyproject.toml` | Edit | Add `"pyttsx3>=2.90"` to `dependencies` |
| `app/cli/voice.py` | **Create** | `TextToSpeech` class with `speak(text)`, `is_available()`, engine init/cleanup |
| `app/cli/main.py` | Edit | Add `/speak` slash command handler; add `--voice` flag to `chat` command; import `TextToSpeech` |
| `app/config/settings.py` | Edit | Add `voice_enabled: bool = False`, `voice_auto_speak: bool = False` |

### Phase 2: CLI STT

| File | Action | Changes |
|------|--------|---------|
| `pyproject.toml` | Edit | Add `"SpeechRecognition>=3.10.0"`, `"pyaudio>=0.2.14"` |
| `app/cli/voice.py` | Edit | Add `SpeechToText` class with `listen()` → returns transcribed text; add `recognize_from_mic(timeout, phrase_limit)` |
| `app/cli/main.py` | Edit | Add `/listen` and `/voice` slash commands; add voice mode state tracking |
| `app/config/settings.py` | Edit | Add `stt_engine: str = "sphinx"`, `stt_timeout: float = 5.0`, `stt_phrase_limit: float = 10.0` |

### Phase 3: Backend API

| File | Action | Changes |
|------|--------|---------|
| `pyproject.toml` | Edit | Add `"openai>=1.0.0"` (if not present), `"google-cloud-texttospeech>=2.0.0"`, `"google-cloud-speech>=2.0.0"` |
| `app/backend/services/voice_service.py` | **Create** | `TTSEngine` class (offline pyttsx3 + cloud OpenAI/Google), `STTEngine` class (offline Sphinx + cloud Whisper/Google), config-driven fallback chain |
| `app/backend/routers/voice.py` | **Create** | `POST /api/tts`, `POST /api/stt`, `GET /api/tts/voices` endpoints with Pydantic models |
| `app/backend/routers/__init__.py` | Edit | Add `voice_router` to imports and `__all__` |
| `app/backend/main.py` | Edit | Add `app.include_router(voice_router)` |
| `app/backend/models/__init__.py` | Edit | Add voice request/response Pydantic models |
| `app/config/settings.py` | Edit | Add `tts_engine: str = "offline"`, `tts_voice: str = ""`, `tts_speed: float = 1.0`, `stt_engine: str = "offline"`, `stt_language: str = "en-US"` |
| `app/backend/tests/test_voice.py` | **Create** | Tests for TTS/STT endpoints |

### Phase 4: UI Integration

| File | Action | Changes |
|------|--------|---------|
| `app/frontend/src/components/ChatPanel.tsx` | Edit | Add mic button in input area; add speaker button per message bubble; add voice mode state |
| `app/frontend/src/hooks/useSpeech.ts` | **Create** | Custom hook wrapping Web Speech API: `useSpeechRecognition()` and `useSpeechSynthesis()` |
| `app/frontend/src/api/client.ts` | Edit | Add `synthesizeSpeech(text)` and `transcribeSpeech(audioBlob)` functions |
| `app/frontend/src/api/types.ts` | Edit | Add `TTSRequest`, `TTSResponse`, `STTRequest`, `STTResponse` types |
| `app/frontend/src/components/VoiceSettings.tsx` | **Create** | Settings panel for voice: auto-speak toggle, voice selector, speed slider |
| `app/frontend/src/store/appStore.ts` | Edit | Add voice settings state (autoSpeak, voiceEnabled, selectedVoice) |

### Phase 5: Cloud Fallback & Quality

| File | Action | Changes |
|------|--------|---------|
| `app/backend/services/voice_service.py` | Edit | Add OpenAI TTS/STT integration; add Google Cloud TTS/STT integration; implement fallback chain logic |
| `app/backend/routers/voice.py` | Edit | Add streaming TTS endpoint (`POST /api/tts/stream` → SSE with audio chunks); add voice list endpoint with cloud voices |
| `app/config/settings.py` | Edit | Add `openai_tts_model: str = "tts-1"`, `openai_tts_voice: str = "alloy"`, `google_tts_voice: str = "en-US-Wavenet-D"` |
| `app/frontend/src/hooks/useSpeech.ts` | Edit | Add streaming audio playback support; add VAD integration |
| `app/frontend/src/components/ChatPanel.tsx` | Edit | Add streaming TTS indicator (audio waveform animation while playing) |

---

## 5. Trade-offs

### 5.1 Offline vs Cloud — TTS

| Criterion | Offline (pyttsx3) | Cloud (OpenAI TTS) | Cloud (Google WaveNet) |
|-----------|-------------------|-------------------|----------------------|
| **Quality** | Robotic, monotone | Natural, expressive | Very natural, multiple voices |
| **Latency** | ~50ms (local) | ~500-1500ms (network) | ~300-1000ms (network) |
| **Cost** | Free | $0.015/1K chars | $0.000016/1K chars (Standard) to $0.00016/1K chars (WaveNet) |
| **Privacy** | Full — no data leaves machine | Text sent to OpenAI | Text sent to Google |
| **Offline capable** | ✅ Yes | ❌ No | ❌ No |
| **Voice variety** | Limited (system voices) | 6 voices (alloy, echo, fable, onyx, nova, shimmer) | 200+ voices, 40+ languages |
| **Setup** | System dep (espeak) | API key only | API key + GCP project |

**Recommendation:** Offline for MVP (Phase 1-2). Cloud as optional upgrade (Phase 5). In UI mode, prefer browser-native Web Speech API (free, zero-latency, no backend).

### 5.2 Offline vs Cloud — STT

| Criterion | Offline (CMU Sphinx) | Cloud (Google STT) | Cloud (OpenAI Whisper) |
|-----------|---------------------|-------------------|----------------------|
| **Accuracy** | ~60-70% (quiet env) | ~95%+ | ~95%+ |
| **Latency** | ~200-500ms (local) | ~500-2000ms (network) | ~1000-3000ms (network) |
| **Cost** | Free | $0.006/15s audio | $0.006/minute |
| **Privacy** | Full — no data leaves | Audio sent to Google | Audio sent to OpenAI |
| **Offline capable** | ✅ Yes | ❌ No | ❌ No |
| **Language support** | English only | 125+ languages | 100+ languages |
| **Noise tolerance** | Low | High | High |

**Recommendation:** Offline Sphinx for MVP (Phase 2). In UI mode, prefer browser Web Speech API (free, good accuracy, no backend). Cloud fallback for noisy environments or non-English (Phase 5).

### 5.3 Latency Comparison (End-to-End)

| Scenario | Estimated Latency | Notes |
|----------|------------------|-------|
| CLI TTS (pyttsx3, offline) | ~50ms + text generation | Text generation dominates |
| UI TTS (Web Speech API) | ~10ms + text generation | Zero network, browser-native |
| UI TTS (backend OpenAI) | ~500ms + text generation + network | Quality trade-off |
| CLI STT (Sphinx, offline) | ~200-500ms | Lower accuracy |
| CLI STT (Google, cloud) | ~500-2000ms | Higher accuracy |
| UI STT (Web Speech API) | ~200-1000ms | Good accuracy, free |

### 5.4 Cost Implications

| Feature | Monthly Cost Estimate (1000 interactions/day) |
|---------|----------------------------------------------|
| Offline TTS (pyttsx3) | $0 |
| Offline STT (Sphinx) | $0 |
| Web Speech API (UI TTS + STT) | $0 |
| OpenAI TTS (cloud) | ~$45/month (at 100 chars/response) |
| OpenAI Whisper (cloud) | ~$18/month (at 5s audio/input) |
| Google STT (cloud) | ~$9/month (at 15s audio/input) |

**Recommendation:** Default to free tiers. Cloud features are opt-in via API keys.

### 5.5 Privacy Implications

| Feature | Data Exposure | Risk Level |
|---------|--------------|------------|
| Offline TTS/STT | None — all local | ✅ None |
| Web Speech API (UI) | Audio processed by browser vendor | ⚠️ Low (browser sandboxed) |
| OpenAI TTS/STT | Text + audio sent to OpenAI | ⚠️ Medium (API key auth, but data leaves machine) |
| Google TTS/STT | Text + audio sent to Google | ⚠️ Medium |

**Recommendation:** Offline-first by default. Show a confirmation dialog before first cloud voice use. Add a privacy mode setting that blocks cloud voice entirely.

---

## 6. API Design

### 6.1 REST Endpoints

#### `POST /api/tts` — Text-to-Speech

Synthesize speech from text.

**Request:**
```json
{
  "text": "Hello, I am YAPOC. How can I help you?",
  "engine": "offline",
  "voice": "",
  "speed": 1.0,
  "format": "wav"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | required | Text to synthesize (max 4096 chars) |
| `engine` | string | `"offline"` | `"offline"`, `"openai"`, `"google"` |
| `voice` | string | `""` | Voice ID (engine-specific; empty = default) |
| `speed` | float | `1.0` | Playback speed (0.5–2.0) |
| `format` | string | `"wav"` | `"wav"`, `"mp3"`, `"ogg"` |

**Response:** `200 OK` with `Content-Type: audio/wav` (or requested format). Binary audio body.

**Error:** `400 Bad Request` — text empty or too long. `503 Service Unavailable` — no TTS engine available.

---

#### `POST /api/stt` — Speech-to-Text

Transcribe uploaded audio to text.

**Request:** `multipart/form-data`

| Field | Type | Description |
|-------|------|-------------|
| `audio` | file (binary) | Audio file (WAV, MP3, OGG, WebM) |
| `engine` | string | `"offline"`, `"openai"`, `"google"` (default: `"offline"`) |
| `language` | string | BCP-47 language code (default: `"en-US"`) |

**Response:**
```json
{
  "text": "list all agents",
  "confidence": 0.92,
  "engine": "offline",
  "duration_ms": 2340
}
```

**Error:** `400 Bad Request` — no audio or unsupported format. `503 Service Unavailable` — no STT engine available.

---

#### `GET /api/tts/voices` — List Available Voices

**Response:**
```json
{
  "engines": {
    "offline": {
      "available": true,
      "voices": [
        {"id": "default", "name": "System Default", "language": "en-US", "gender": ""}
      ]
    },
    "openai": {
      "available": true,
      "voices": [
        {"id": "alloy", "name": "Alloy", "language": "en-US", "gender": "neutral"},
        {"id": "echo", "name": "Echo", "language": "en-US", "gender": "male"},
        {"id": "fable", "name": "Fable", "language": "en-GB", "gender": "neutral"},
        {"id": "onyx", "name": "Onyx", "language": "en-US", "gender": "male"},
        {"id": "nova", "name": "Nova", "language": "en-US", "gender": "female"},
        {"id": "shimmer", "name": "Shimmer", "language": "en-US", "gender": "female"}
      ]
    },
    "google": {
      "available": false,
      "voices": []
    }
  }
}
```

---

#### `POST /api/tts/stream` — Streaming TTS (Phase 5)

Stream audio chunks via SSE for real-time playback.

**Request:** Same as `POST /api/tts` but with `"stream": true`.

**Response:** `text/event-stream`

```
data: {"type": "audio_start", "format": "wav", "sample_rate": 24000}
data: {"type": "audio_chunk", "data": "<base64-encoded bytes>", "index": 0}
data: {"type": "audio_chunk", "data": "<base64-encoded bytes>", "index": 1}
data: {"type": "audio_end", "total_chunks": 12, "duration_ms": 3200}
```

---

### 6.2 WebSocket Messages (Future)

For real-time voice in the UI, the existing `/ws` WebSocket could be extended with voice events:

| Direction | Type | Payload | Description |
|-----------|------|---------|-------------|
| Server → Client | `voice_tts_chunk` | `{text, audio_base64?, index, final}` | TTS audio chunk during streaming response |
| Client → Server | `voice_stt_chunk` | `{audio_base64, index, final}` | Streaming STT audio from browser mic |

This is **Phase 5+** — the initial implementation uses REST for simplicity.

### 6.3 Pydantic Models

```python
# app/backend/models/voice.py

from pydantic import BaseModel, Field
from typing import Literal


class TTSRequest(BaseModel):
    text: str = Field(..., max_length=4096, description="Text to synthesize")
    engine: Literal["offline", "openai", "google"] = "offline"
    voice: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["wav", "mp3", "ogg"] = "wav"
    stream: bool = False


class TTSVoice(BaseModel):
    id: str
    name: str
    language: str
    gender: str


class TTSVoicesResponse(BaseModel):
    engines: dict[str, dict]


class STTRequest(BaseModel):
    engine: Literal["offline", "openai", "google"] = "offline"
    language: str = "en-US"


class STTResponse(BaseModel):
    text: str
    confidence: float = 0.0
    engine: str
    duration_ms: int = 0
```

### 6.4 Streaming Considerations

1. **TTS streaming:** For long responses (>200 chars), streaming audio chunks via SSE allows the browser to start playback before synthesis completes. The frontend buffers chunks and plays them sequentially via `AudioContext`.

2. **STT streaming:** For continuous dictation, the Web Speech API already provides interim results (`isFinal: false`). The backend STT endpoint accepts complete audio only — streaming STT is a future enhancement.

3. **Backpressure:** The TTS engine should respect backpressure from the audio output device. pyttsx3 handles this internally (blocking `say()`). For cloud TTS, the streaming endpoint should throttle chunk generation to match real-time playback speed.

4. **Timeout:** TTS requests should timeout after 30s for cloud engines. STT audio uploads should be limited to 60s of audio.

---

## Appendix A: CLI Voice Commands

| Command | Description |
|---------|-------------|
| `/speak` | Read the last assistant response aloud |
| `/listen` | Capture microphone input and transcribe to text |
| `/voice` | Toggle continuous voice mode (listen → send → listen loop) |
| `/voice stop` | Exit voice mode |
| `/voice speed <0.5-2.0>` | Adjust TTS speed |
| `/voice engine <offline|openai|google>` | Switch TTS engine |

## Appendix B: UI Voice Controls

| Control | Location | Description |
|---------|----------|-------------|
| 🎤 Mic button | ChatPanel input area, right side | Toggle STT listening |
| 🔊 Speaker icon | Each assistant message bubble | Read that message aloud |
| ⚙️ Voice settings | Settings panel (gear icon) | Auto-speak toggle, voice selector, speed slider |
| 🎵 Audio waveform | During TTS playback | Visual indicator of audio playing |

## Appendix C: Configuration (.env)

```bash
# Voice feature
VOICE_ENABLED=false
VOICE_AUTO_SPEAK=false

# TTS engine selection: offline | openai | google
TTS_ENGINE=offline
TTS_VOICE=
TTS_SPEED=1.0

# STT engine selection: offline | openai | google
STT_ENGINE=offline
STT_LANGUAGE=en-US
STT_TIMEOUT=5.0
STT_PHRASE_LIMIT=10.0

# Cloud TTS/STT (optional, requires API keys)
OPENAI_TTS_MODEL=tts-1
OPENAI_TTS_VOICE=alloy
GOOGLE_TTS_VOICE=en-US-Wavenet-D
```
