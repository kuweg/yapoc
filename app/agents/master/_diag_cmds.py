import httpx

print("base_url:", __import__("app.config", fromlist=["settings"]).settings.base_url)
print("host:", __import__("app.config", fromlist=["settings"]).settings.host)
print("port:", __import__("app.config", fromlist=["settings"]).settings.port)

for label, url in [
    ("localhost /health", "http://localhost:8000/health"),
    ("127.0.0.1 /health", "http://127.0.0.1:8000/health"),
]:
    try:
        r = httpx.get(url, timeout=5)
        print(f"{label}: {r.status_code} {r.text[:80]}")
    except Exception as e:
        print(f"{label}: EXC {type(e).__name__}: {e}")

# hit the command endpoint
for cmd in ["/status", "/ping", "/agents", "/model", "/cost", "/sessions"]:
    try:
        r = httpx.post("http://127.0.0.1:8000/api/commands", json={"command": cmd, "args": ""}, timeout=10)
        print(f"--- {cmd} -> {r.status_code}")
        print(r.text[:400])
    except Exception as e:
        print(f"--- {cmd} -> EXC {type(e).__name__}: {e}")
