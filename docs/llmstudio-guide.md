# LM Studio + YAPOC — Local Model Setup Guide

LM Studio runs open-weight LLMs on your own machine and exposes them behind an
OpenAI-compatible HTTP server. YAPOC's `lmstudio` adapter speaks that protocol,
so any model you load in LM Studio becomes available to any agent by pointing
its `CONFIG.md` at the `lmstudio` adapter.

## Why use LM Studio with YAPOC

- **Offline / private** — no data leaves your machine.
- **Zero cost** — local inference is free (only electricity).
- **Drop-in OpenAI compatible** — the existing `OpenAIAdapter` normalization
  path is reused, so tool-use and streaming work the same way as with the
  hosted providers.
- **Good for Doctor / Keeper / Cron** — agents that run on a schedule and don't
  need frontier intelligence are ideal candidates for local fallbacks.

## 1. Install LM Studio

1. Go to <https://lmstudio.ai> and download the build for your OS
   (macOS / Windows / Linux).
2. Install and launch it.

## 2. Download a model

In the app:

1. Open the **Discover** tab (magnifier icon in the left sidebar).
2. Search for a tool-use-capable instruct model. Good starting points on Apple
   Silicon / modern x86:
   - `lmstudio-community/Qwen2.5-7B-Instruct-GGUF` — fast, supports tools,
     fits in ~8 GB RAM.
   - `lmstudio-community/Qwen2.5-Coder-32B-Instruct-GGUF` — excellent for
     Builder/Planning if you have ≥32 GB RAM.
   - `lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF` — general-purpose.
   - `lmstudio-community/Mistral-Small-Instruct-2409-GGUF` — strong tool use.
3. Click a quantization (Q4_K_M is a good balance of speed and quality) and
   **Download**.

> **Note**: YAPOC's Builder, Master, and Planning agents use multi-turn tool
> use. Pick a model whose card explicitly says "supports tool / function
> calling", otherwise tool calls will silently be ignored.

## 3. Start the local server

1. Click the **Developer** tab in the left sidebar (or the `<>` icon).
2. At the top, click **Select a model to load** and choose the one you
   downloaded. Wait for it to finish loading into memory.
3. Toggle **Start Server** (the big power button). You should see a green
   status bar showing the URL, typically:

   ```
   http://localhost:1234/v1
   ```

4. Leave this app running while you use YAPOC.

## 4. Point YAPOC at LM Studio

### 4a. Verify the adapter

YAPOC's `lmstudio` adapter is already registered. Confirm with:

```bash
poetry run python -c "from app.utils.adapters import ADAPTER_REGISTRY; print('lmstudio' in ADAPTER_REGISTRY)"
```

Should print `True`.

### 4b. Environment variables

In `.env`:

```bash
# Usually this is the default — no need to change unless you customized the
# LM Studio server port.
LMSTUDIO_BASE_URL=http://localhost:1234

# LM Studio runs keyless by default; leave blank unless you enabled API auth
# under Developer → Server Settings → Require API key.
LMSTUDIO_API_KEY=
```

### 4c. Set an agent's model to an LM Studio model

Edit e.g. `app/agents/doctor/CONFIG.md`:

```yaml
adapter: lmstudio
model: lmstudio-community/Qwen2.5-7B-Instruct-GGUF
temperature: 0.2
tools:
  - file_read
  - file_list
  - read_agent_logs
  - memory_append
  - notes_read
  - notes_write
  - health_log
runner:
  max_turns: 10
  task_timeout: 300   # ← bump this, local inference is slower than hosted
```

The `model` field must match **exactly** the identifier LM Studio shows on the
Developer tab next to the loaded model.

### 4d. Smoke test

```bash
poetry run python -c "
import asyncio
from app.utils.adapters import AgentConfig, get_adapter

async def main():
    cfg = AgentConfig(
        adapter='lmstudio',
        model='lmstudio-community/Qwen2.5-7B-Instruct-GGUF',  # change to what you loaded
        temperature=0.2,
    )
    adapter = get_adapter(cfg)
    out = await adapter.complete(
        system_prompt='You are a terse assistant.',
        user_message='Say hi in one word.',
    )
    print('LM Studio says:', out)

asyncio.run(main())
"
```

If you see a one-word hi, you're wired up.

## 5. Use LM Studio as a fallback

Edit `app/agents/doctor/agent-settings-base.json` and add an LM Studio fallback
to any agent:

```json
{
  "agent": "doctor",
  "model": {
    "name": "gpt-4o-mini",
    "adapter": "openai",
    "key_env": "OPENAI_API_KEY",
    "key": ""
  },
  "fallbacks": [
    {
      "model": {
        "name": "lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
        "adapter": "lmstudio",
        "key_env": "LMSTUDIO_API_KEY",
        "key": ""
      }
    }
  ]
}
```

Remember to increase `DEFAULT_N_FALLBACKS_MODELS` in `.env` if you want more
than one fallback honored.

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `httpx.ConnectError` | LM Studio server not running | Toggle **Start Server** in the Developer tab. |
| `404 Not Found` | Wrong model id in CONFIG.md | Copy the exact id shown under the loaded model in LM Studio. |
| Agent hangs, never replies | First turn after loading is slow (model warm-up) | Bump `task_timeout` in CONFIG.md and retry. |
| `400 This model does not support tools` | Loaded model has no tool-use capability | Load a different model (Qwen2.5, Mistral Small, Llama 3.1). |
| JSON parse errors in tool calls | Small models sometimes emit broken JSON | Lower `temperature` (0.0–0.2) or use a larger quantization. |
| Cost tracking shows `$0.0000` | Expected — local models are free in `ALL_PRICING`. | — |

## 7. Performance tips

- **Pick the right quantization.** `Q4_K_M` is a good balance; `Q5_K_M` gives
  better quality at a memory/speed cost; `Q3_K_S` fits in less RAM but degrades
  noticeably on reasoning.
- **Bump context only as far as you need.** In LM Studio → Developer →
  Model Settings, raise the context length to at least 16 k for Builder/Master
  agents; 32 k+ for Planning.
- **Use one agent at a time** on a single machine if you're compute-limited.
  Spawning several concurrent agents that all hit LM Studio will queue them
  serially.
- **Keep `max_tokens` modest.** 2 048–4 096 is usually enough for agent
  responses.

## 8. When to pick LM Studio vs Ollama

Both expose local models via OpenAI-compatible servers. Choose LM Studio when:

- You want a GUI to download/manage models.
- You want to swap quantizations interactively.
- You want to see GPU/CPU load visualizations.

Choose Ollama when:

- You want a lightweight CLI-only daemon.
- You're running headless on a server.

YAPOC supports both simultaneously — pick per agent.
