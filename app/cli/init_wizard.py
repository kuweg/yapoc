"""Interactive first-run wizard — `poetry run yapoc init`.

Picks a provider, validates the key with a live probe, writes a sensible
``.env`` from the existing ``.env.example`` template, and rewrites
``app/config/agent-settings.json`` so every agent uses the chosen provider
as primary. Existing fallback chains and per-agent tuning are preserved.

Safe to re-run. An existing ``.env`` is backed up to ``.env.bak.<unix>``
before being overwritten.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

from app.config import settings
from app.utils.adapters.health import check_provider
from app.utils.adapters.models import PROVIDER_MODELS


console = Console()


PROVIDER_DISPLAY: dict[str, str] = {
    "anthropic": "Anthropic           — Claude (cloud)",
    "openai": "OpenAI              — GPT (cloud)",
    "deepseek": "DeepSeek            — deepseek-chat (cloud, cheap)",
    "openrouter": "OpenRouter          — multi-provider aggregator (cloud)",
    "google": "Google Gemini       — Gemini (cloud)",
    "codex": "OpenAI Codex        — code-specialised (uses OPENAI_API_KEY)",
    "ollama": "Ollama              — local LLM server",
    "lmstudio": "LM Studio           — local LLM server",
}

PROVIDER_ENV_KEY: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "codex": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_API_KEY",
    "lmstudio": "LMSTUDIO_API_KEY",
}

PROVIDER_BASE_URL_KEY: dict[str, str] = {
    "ollama": "OLLAMA_BASE_URL",
    "lmstudio": "LMSTUDIO_BASE_URL",
}

DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234",
}

# Top-3 starter models per provider — shown in the wizard's model picker.
# Full lists live in app/utils/adapters/models/<provider>.py; this is just
# the curated subset a newcomer should see first.
STARTER_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-5.4-mini", "gpt-5.4", "gpt-4.1-nano"],
    "codex": ["gpt-5.1-codex", "gpt-5.2"],
    "deepseek": ["deepseek-chat", "deepseek-v4-pro"],
    "openrouter": ["anthropic/claude-sonnet-4-6", "openai/gpt-5.4-mini"],
    "google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
    "ollama": ["llama3.1:8b", "qwen2.5-coder:32b"],
    "lmstudio": ["local-model"],
}


def run_wizard(noninteractive: bool = False) -> int:
    """Run the interactive setup wizard. Returns shell exit code."""
    if noninteractive:
        console.print(
            "[red]Wizard cannot run non-interactively.[/red] "
            "Use --offline or fill .env manually."
        )
        return 1

    console.print(
        "\n[bold yellow]YAPOC setup[/bold yellow]"
        " [dim]— pick a provider, validate the key, write .env.[/dim]\n"
    )

    env_path = settings.project_root / ".env"
    if env_path.exists() and env_path.read_text(encoding="utf-8").strip():
        choice = questionary.select(
            ".env already exists. What now?",
            choices=[
                "Keep existing .env — exit",
                "Reconfigure (existing .env will be backed up)",
            ],
        ).ask()
        if not choice or choice.startswith("Keep"):
            console.print("[dim]No changes made.[/dim]")
            return 0

    provider = questionary.select(
        "Which LLM provider do you want as the default?",
        choices=[
            questionary.Choice(title=PROVIDER_DISPLAY[p], value=p)
            for p in PROVIDER_DISPLAY
        ],
    ).ask()
    if not provider:
        return 1

    api_key, base_url = _collect_credentials(provider)
    if api_key is None and provider in PROVIDER_ENV_KEY:
        return 1

    api_key = _validate_loop(provider, api_key, base_url)
    if api_key is None:
        return 1

    model = _pick_model(provider)
    if not model:
        return 1

    install_frontend = questionary.confirm(
        "Install the web UI too? (requires Node 20+ and pnpm)",
        default=False,
    ).ask()
    if install_frontend is None:
        install_frontend = False

    _write_env(env_path, provider, api_key, base_url, model)
    console.print(f"[green]wrote[/green] {env_path.relative_to(settings.project_root)}")

    _rewrite_agent_settings(provider, model)
    console.print(
        "[green]wrote[/green] app/config/agent-settings.json"
        f" [dim](all 11 agents → {provider} / {model})[/dim]"
    )

    _ensure_data_dirs()

    if install_frontend:
        _install_frontend()

    _print_summary(provider, model, install_frontend)
    return 0


# ── steps ────────────────────────────────────────────────────────────────────


def _collect_credentials(provider: str) -> tuple[str | None, str]:
    """Prompt for API key and/or base URL. Returns (api_key, base_url)."""
    api_key: str | None = ""
    base_url = ""

    env_key_name = PROVIDER_ENV_KEY.get(provider)
    if env_key_name:
        suffix = ""
        if provider == "lmstudio":
            suffix = " (leave blank if LM Studio runs without auth)"
        api_key = questionary.password(
            f"Paste your {provider} API key ({env_key_name}){suffix}"
        ).ask()

    if provider in PROVIDER_BASE_URL_KEY:
        base_url = (
            questionary.text(
                f"{provider} base URL",
                default=DEFAULT_BASE_URLS[provider],
            ).ask()
            or DEFAULT_BASE_URLS[provider]
        )

    return api_key, base_url


def _validate_loop(provider: str, api_key: str | None, base_url: str) -> str | None:
    """Live-validate credentials, with retry/skip/cancel on failure."""
    while True:
        with console.status(f"[dim]validating {provider} credentials…[/dim]"):
            ok, msg = asyncio.run(
                check_provider(provider, api_key=api_key or "", base_url=base_url)
            )

        if ok:
            console.print(f"[green]ok[/green] {msg}")
            return api_key or ""

        console.print(f"[red]fail[/red] {msg}")
        next_step = questionary.select(
            "What now?",
            choices=[
                "Retry — re-enter key",
                "Save anyway (skip validation)",
                "Cancel",
            ],
        ).ask()
        if next_step is None or next_step.startswith("Cancel"):
            console.print("[yellow]Wizard cancelled.[/yellow]")
            return None
        if next_step.startswith("Save"):
            return api_key or ""

        env_key_name = PROVIDER_ENV_KEY.get(provider)
        if env_key_name:
            api_key = questionary.password(f"Re-enter {env_key_name}").ask()
            if api_key is None:
                return None


def _pick_model(provider: str) -> str | None:
    """Show a short list of starter models for the chosen provider."""
    choices = STARTER_MODELS.get(provider) or PROVIDER_MODELS.get(provider, [])[:6]
    if not choices:
        return questionary.text(
            f"No catalog for {provider} — type a model id:"
        ).ask() or None

    return questionary.select(
        f"Default model for {provider}:",
        choices=choices,
        default=choices[0],
    ).ask()


def _write_env(
    path: Path, provider: str, api_key: str, base_url: str, model: str
) -> None:
    """Render .env from .env.example, substituting the answered fields.

    Backs up any existing .env to .env.bak.<unix> before writing.
    """
    example_path = settings.project_root / ".env.example"
    template = (
        example_path.read_text(encoding="utf-8") if example_path.exists() else ""
    )

    if path.exists():
        backup = path.with_name(f".env.bak.{int(time.time())}")
        shutil.copy2(path, backup)
        console.print(f"[dim]backed up existing .env to {backup.name}[/dim]")

    updates: dict[str, str] = {
        "DEFAULT_ADAPTER": provider,
        "DEFAULT_MODEL": model,
    }
    env_key_name = PROVIDER_ENV_KEY.get(provider)
    if env_key_name and api_key:
        updates[env_key_name] = api_key
    if base_url and provider in PROVIDER_BASE_URL_KEY:
        updates[PROVIDER_BASE_URL_KEY[provider]] = base_url

    out_lines: list[str] = []
    seen: set[str] = set()
    for line in template.splitlines():
        stripped = line.lstrip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out_lines.append(line)

    for k, v in updates.items():
        if k not in seen:
            out_lines.append(f"{k}={v}")

    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _rewrite_agent_settings(provider: str, model: str) -> None:
    """Repoint every agent's primary adapter/model. Preserves fallbacks + tuning."""
    path = settings.project_root / "app" / "config" / "agent-settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for cfg in data.get("agents", {}).values():
        cfg["adapter"] = provider
        cfg["model"] = model
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ensure_data_dirs() -> None:
    """Create directories the app expects but does not auto-create."""
    for relpath in ("app/projects", "data/sessions"):
        d = settings.project_root / relpath
        d.mkdir(parents=True, exist_ok=True)


def _install_frontend() -> None:
    """Run `pnpm install` in app/frontend. Skip with a clear hint if pnpm missing."""
    pnpm = shutil.which("pnpm")
    frontend = settings.project_root / "app" / "frontend"
    if not frontend.exists():
        console.print("[dim]no app/frontend/ — skipping frontend install[/dim]")
        return
    if not pnpm:
        console.print(
            "[yellow]pnpm not found.[/yellow] Install Node 20+, then run "
            "[bold]corepack enable && corepack prepare pnpm@latest --activate[/bold]. "
            "Skipping frontend install."
        )
        return
    console.print(f"[dim]pnpm install ({frontend})…[/dim]")
    result = subprocess.run([pnpm, "install"], cwd=frontend)
    if result.returncode != 0:
        console.print(f"[red]pnpm install failed (exit {result.returncode})[/red]")
    else:
        console.print("[green]ok[/green] frontend deps installed")


def _print_summary(provider: str, model: str, frontend: bool) -> None:
    table = Table(title="Setup complete", show_header=False, title_style="bold yellow")
    table.add_column("", style="bold")
    table.add_column("")
    table.add_row("Provider", provider)
    table.add_row("Default model", model)
    table.add_row("Frontend", "installed" if frontend else "skipped")
    console.print(table)
    console.print(
        "\n[bold]next steps:[/bold]\n"
        "  [dim]poetry run yapoc doctor[/dim]   # preflight check\n"
        "  [dim]poetry run yapoc start[/dim]    # start the backend daemon\n"
        "  [dim]poetry run yapoc[/dim]          # interactive REPL"
    )
