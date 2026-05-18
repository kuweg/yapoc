import httpx
import sys

BASE = "http://localhost:8000"

# 1. Check if server is running
print("=== Step 1: Check /api/tts/voices ===")
try:
    r = httpx.get(f"{BASE}/api/tts/voices", timeout=10)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")
except Exception as e:
    print(f"ERROR: {e}")

# 2. Test OpenAI TTS
print("\n=== Step 2: Test /api/tts with engine=openai ===")
try:
    payload = {
        "text": "Hello, this is a test of the OpenAI TTS engine.",
        "engine": "openai",
        "voice": "alloy",
        "speed": 1.0,
        "fmt": "mp3"
    }
    r = httpx.post(f"{BASE}/api/tts", json=payload, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Headers: {dict(r.headers)}")
    print(f"Content length: {len(r.content)} bytes")
    if r.status_code == 200:
        with open("app/test_tts_output.mp3", "wb") as f:
            f.write(r.content)
        print("Saved to app/test_tts_output.mp3")
    else:
        print(f"Error body: {r.text[:500]}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== Done ===")
