"""Slash command handler for the CLI and UI.

Provides a single `handle_command(command_name, args)` function that
returns a dict with ``message`` and ``type`` keys.

Usage::

    result = handle_command("ping", [])
    # => {"message": "pong", "type": "success"}
"""

from __future__ import annotations

from typing import Any


def handle_command(command_name: str, args: list[str]) -> dict[str, Any]:
    """Dispatch a slash command and return a result dict.

    Parameters
    ----------
    command_name : str
        The command name without the leading ``/`` (e.g. ``"ping"``).
    args : list[str]
        Any additional arguments passed after the command name.

    Returns
    -------
    dict[str, Any]
        A dict with ``"message"`` (str) and ``"type"`` (str) keys.
        ``type`` is one of ``"success"``, ``"error"``, or ``"info"``.
    """
    cmd = command_name.strip().lower()

    # ── Static / simple commands ──────────────────────────────────────────

    if cmd == "ping":
        return {"message": "pong", "type": "success"}

    if cmd == "help":
        return {
            "message": (
                "Available commands: /help, /clear, /ping, /status, /agents, "
                "/model, /cost, /sessions, /continue, /resume <id>, "
                "/export <filename>, /doctor, /start, /stop, /restart, /exit"
            ),
            "type": "info",
        }

    if cmd == "status":
        return {"message": "All systems nominal", "type": "info"}

    if cmd == "agents":
        return {
            "message": "Master, Planning, Builder, Keeper, Doctor, Cron, Model Manager",
            "type": "info",
        }

    if cmd == "model":
        return {"message": "See agent settings for model details", "type": "info"}

    if cmd == "cost":
        return {"message": "Cost tracking available in UI cost bar", "type": "info"}

    if cmd == "sessions":
        return {"message": "No sessions found", "type": "info"}

    if cmd == "clear":
        return {"message": "Conversation cleared", "type": "success"}

    if cmd == "exit":
        return {"message": "No-op in web UI", "type": "info"}

    if cmd == "doctor":
        return {"message": "Doctor agent is running", "type": "info"}

    if cmd == "start":
        return {"message": "Server already running", "type": "info"}

    if cmd == "stop":
        return {"message": "Cannot stop server from web UI", "type": "error"}

    if cmd == "restart":
        return {"message": "Restart requested", "type": "info"}

    if cmd == "continue":
        return {"message": "Continuing session...", "type": "info"}

    # ── Commands that accept arguments ────────────────────────────────────

    if cmd == "resume":
        session_id = args[0] if args else ""
        return {"message": f"Resuming session {session_id}", "type": "info"}

    if cmd == "export":
        filename = args[0] if args else "output.txt"
        return {"message": f"Exporting to {filename}", "type": "info"}

    # ── Fallback ──────────────────────────────────────────────────────────

    return {"message": f"Unknown command: /{command_name}", "type": "error"}
