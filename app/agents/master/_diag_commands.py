import httpx

base = "http://127.0.0.1:8000"

# Test the actual command endpoint both with and without /api prefix
for path in ["/api/commands", "/commands"]:
    try:
        r = httpx.post(base + path, json={"command": "/ping"}, timeout=10)
        print(f"POST {path} -> {r.status_code} {r.text[:200]!r}")
    except Exception as e:
        print(f"POST {path} -> {type(e).__name__}: {e}")

print()
# Test /status and /agents commands
for path in ["/api/commands", "/commands"]:
    try:
        r = httpx.post(base + path, json={"command": "/status"}, timeout=10)
        print(f"POST {path} /status -> {r.status_code} {r.text[:300]!r}")
    except Exception as e:
        print(f"POST {path} /status -> {type(e).__name__}: {e}")
