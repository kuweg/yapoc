"""Credential/configuration stages of the cross-platform installer.

The host launcher selects and mounts the working folder first. Credentials are
collected here, never placed in shell arguments, Compose files, or image layers.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

import httpx
import questionary
from dotenv import dotenv_values
from rich.console import Console

from app.config import settings
from app.cli.init_wizard import (
    PROVIDER_DISPLAY, PROVIDER_ENV_KEY, _collect_credentials, _validate_loop,
    _pick_model, _write_env, _ensure_data_dirs,
)

console = Console()


def telegram_call(client: httpx.Client, token: str, method: str, **params):
    """Avoid rendering exception URLs, which contain the bot credential."""
    try:
        response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=params)
        body = response.json()
        if not response.is_success or not body.get("ok"):
            raise ValueError("Telegram rejected the request. Check the token and ensure no other bot process is polling.")
        return body["result"]
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise ValueError("Could not reach Telegram. Check your connection and retry.") from None


def pair_telegram(token: str, *, timeout: float = 180) -> int:
    with httpx.Client(timeout=30) as client:
        bot = telegram_call(client, token, "getMe")
        webhook = telegram_call(client, token, "getWebhookInfo")
        if webhook.get("url"):
            raise ValueError("This bot already has a webhook. Create a dedicated YAPOC bot with @BotFather.")
        nonce = "yapoc_" + secrets.token_hex(12)
        console.print(f"Open https://t.me/{bot['username']}?start={nonce} and press Start.", markup=False)
        console.print("Waiting for your private chat (up to 3 minutes; Ctrl+C cancels)…")
        deadline = time.monotonic() + timeout
        offset = 0
        while time.monotonic() < deadline:
            updates = telegram_call(client, token, "getUpdates", offset=offset, timeout=10,
                                    allowed_updates=["message"])
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                message = update.get("message", {})
                chat = message.get("chat", {})
                if chat.get("type") == "private" and message.get("text") == f"/start {nonce}":
                    # Acknowledge the pairing update so startup does not turn it
                    # into a master task. No notification is sent during setup.
                    telegram_call(client, token, "getUpdates", offset=offset, timeout=0)
                    return int(chat["id"])
        raise ValueError("Pairing timed out. Retry and press Start in the bot's private chat.")


def configure_agents(root: Path, provider: str, model: str) -> None:
    path = root / "app/config/agent-settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for cfg in data.get("agents", {}).values():
        cfg.update(adapter=provider, model=model)
        # A new user authorized this provider only. Do not inherit the
        # developer's cross-provider fallback chain from the release template.
        cfg["fallbacks"] = [f for f in cfg.get("fallbacks", []) if f.get("adapter") == provider and f.get("model") == model]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_guided_setup() -> int:
    root = settings.project_root
    if not (root / ".yapoc-install.json").exists():
        console.print("Run the guided host installer first: node installer/index.mjs --source .")
        return 1
    env_path = root / ".env"
    try:
        if env_path.exists():
            choice = questionary.select("Existing setup found", choices=[
                "Keep settings and start YAPOC", "Reconfigure", "Cancel",
            ]).ask()
            if not choice or choice == "Cancel":
                return 1
            if choice.startswith("Keep"):
                return 0

        console.print("\n[bold]2/5 — Connect an allowed AI provider[/bold]")
        # The initial guided release uses cloud providers; local endpoints in
        # containers need an explicit host address rather than localhost.
        providers = [p for p in PROVIDER_DISPLAY if p in PROVIDER_ENV_KEY and p != "lmstudio"]
        provider = questionary.select("Provider", choices=[
            questionary.Choice(PROVIDER_DISPLAY[p], value=p) for p in providers
        ]).ask()
        if not provider:
            return 1
        key, base_url = _collect_credentials(provider)
        if not key:
            return 1
        key = _validate_loop(provider, key, base_url)
        if key is None:
            return 1
        model = _pick_model(provider)
        if not model:
            return 1

        console.print("\n[bold]3/5 — Optional Telegram notifications[/bold]")
        wants_telegram = questionary.confirm("Connect a Telegram bot?", default=False).ask()
        if wants_telegram is None:
            return 1
        telegram = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_WHITELIST": "[]", "TELEGRAM_AUTH_PIN": ""}
        while wants_telegram:
            console.print("Create a dedicated bot with @BotFather and paste its bot token.")
            token = questionary.password("Telegram bot token").ask()
            if not token:
                return 1
            try:
                chat_id = pair_telegram(token)
                telegram = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_WHITELIST": json.dumps([chat_id]),
                            "TELEGRAM_AUTH_PIN": secrets.token_urlsafe(32)}
                break
            except ValueError as exc:
                console.print(str(exc), markup=False)
                action = questionary.select("Telegram setup", choices=["Retry", "Skip Telegram", "Cancel"]).ask()
                if not action or action == "Cancel":
                    return 1
                wants_telegram = action == "Retry"

        console.print("\n[bold]4/5 — Save configuration and prepare YAPOC[/bold]")
        existing = dotenv_values(env_path, interpolate=False) if env_path.exists() else {}
        access_token = existing.get("BACKEND_API_TOKEN") or secrets.token_urlsafe(32)
        updates = {"BACKEND_API_TOKEN": access_token, "HOST": "0.0.0.0", "PORT": "8000",
                   "REDIS_URL": "redis://redis:6379", "MANAGED_RESTART": "true", **telegram}
        _write_env(env_path, provider, key, base_url, model, updates)
        configure_agents(root, provider, model)
        _ensure_data_dirs()
        console.print("Configuration saved. The installer will start YAPOC and open your browser.")
        return 0
    except (KeyboardInterrupt, EOFError):
        console.print("\nSetup cancelled. Re-run the installer to continue.")
        return 1
