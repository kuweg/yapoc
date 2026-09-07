"""Configuration loading for the YAPOC MCP host layer.

Reads ``mcp-servers.json`` from the project root, resolves ``${VAR}``
references against ``.env`` / ``os.environ``, and returns a validated
:class:`MCPConfig`.

Missing file or malformed JSON never crashes startup — an empty config
is returned instead.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .types import MCPServerConfig, MCPConfig

logger = logging.getLogger(__name__)

# Matches ${VAR} and ${VAR:-default} references.
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _try_load_dotenv(project_root: Path) -> None:
    """Best-effort load of the root ``.env`` into ``os.environ``.

    Uses ``python-dotenv`` if present; silently ignores failure so the
    absence of ``.env`` or ``dotenv`` never breaks config loading.
    """
    env_file = project_root / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except Exception:  # pragma: no cover - defensive
        logger.debug("dotenv unavailable; skipping .env load", exc_info=True)


def _resolve(value: str) -> str:
    """Resolve ``${VAR}`` and ``${VAR:-default}`` references to env values.

    A reference with no value and no default is resolved to an empty
    string rather than raising.
    """

    def _sub(match: "re.Match[str]") -> str:
        var, default = match.group(1), match.group(2)
        if var in os.environ:
            return os.environ[var]
        if default is not None:
            return default
        return ""

    if not isinstance(value, str):
        return value
    if "${" not in value:
        return value
    return _ENV_REF_RE.sub(_sub, value)


def _resolve_env_dict(env: Any) -> dict[str, str]:
    """Resolve a parsed ``env`` object (dict of str) resolving ``${VAR}``."""
    if not isinstance(env, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, val in env.items():
        if not isinstance(val, str):
            continue
        resolved[str(key)] = _resolve(val)
    return resolved


def _parse_server(raw: Any) -> MCPServerConfig:
    """Parse one raw server dict into an :class:`MCPServerConfig`.

    Unknown/odd types in individual fields are coerced to a safe default
    rather than raising a hard validation error.
    """
    if not isinstance(raw, dict):
        return MCPServerConfig()
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        logger.warning("MCP server entry missing/invalid 'name'; skipping entry")
        return MCPServerConfig(name="")
    transport = raw.get("transport", "stdio")
    if not isinstance(transport, str):
        transport = "stdio"

    # A skipped entry carries the marker name "" so callers can drop it.
    cfg = MCPServerConfig(name=name, transport=transport)
    _assign_str(cfg, "command", raw.get("command"))
    _assign_str(cfg, "url", raw.get("url"))
    _assign_str(cfg, "auth", raw.get("auth"), default="none")
    _assign_str(cfg, "api_key", raw.get("api_key"))
    _assign_str(cfg, "token", raw.get("token"))

    args = raw.get("args")
    if isinstance(args, list):
        # Args go through _resolve like every other string field, so a server
        # entry can carry a machine-dependent value (a browser path, a port)
        # as ${VAR:-default} instead of hard-coding one developer's layout.
        cfg.args = [
            _resolve(str(a)) for a in args if isinstance(a, (str, int, float))
        ]

    tools_allow = raw.get("tools_allowlist")
    if isinstance(tools_allow, list):
        cfg.tools_allowlist = [str(x) for x in tools_allow if isinstance(x, str)]
    if raw.get("tools_allowlist") is None:
        cfg.tools_allowlist = ["*"]

    res_allow = raw.get("resources_allowlist")
    if isinstance(res_allow, list):
        cfg.resources_allowlist = [str(x) for x in res_allow if isinstance(x, str)]
    if raw.get("resources_allowlist") is None:
        cfg.resources_allowlist = ["*"]

    if isinstance(raw.get("timeout_s"), (int, float)):
        cfg.timeout_s = int(raw["timeout_s"])
    if isinstance(raw.get("enabled"), bool):
        cfg.enabled = raw["enabled"]
    if isinstance(raw.get("auto_reconnect"), bool):
        cfg.auto_reconnect = raw["auto_reconnect"]

    # Resolve secret-bearing env / api_key / token from .env.
    cfg.env = _resolve_env_dict(raw.get("env"))
    cfg.api_key = _resolve(cfg.api_key)
    cfg.token = _resolve(cfg.token)

    return cfg


def _assign_str(cfg: MCPServerConfig, attr: str, value: Any, default: str = "") -> None:
    """Assign ``value`` to ``cfg.<attr>`` only if it is a string."""
    if isinstance(value, str):
        setattr(cfg, attr, value)
    else:
        setattr(cfg, attr, default)


def load_mcp_config(project_root: Path | None = None) -> MCPConfig:
    """Load and validate ``mcp-servers.json`` at the project root.

    Args:
        project_root: Optional explicit project root. When omitted it is
            derived from the ``app`` package location so this function
            works whether or not ``app.config.settings`` was imported.

    Returns:
        An :class:`MCPConfig`. Empty when the file is missing, unreadable,
        or contains malformed JSON — never raises.
    """
    if project_root is None:
        try:
            from app.config.settings import settings

            project_root = settings.project_root
        except Exception:  # pragma: no cover - defensive fallback
            project_root = Path(__file__).resolve().parent.parent.parent  # app/ → root

    project_root = Path(project_root)
    # Give .env a chance to populate env vars before resolving ${VAR}.
    _try_load_dotenv(project_root)

    config_path = project_root / "mcp-servers.json"
    if not config_path.exists():
        logger.info("mcp-servers.json not found at %s; returning empty MCP config", config_path)
        return MCPConfig()

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse %s: %s; returning empty MCP config", config_path, exc)
        return MCPConfig()

    if not isinstance(data, dict):
        logger.warning("mcp-servers.json root must be an object; returning empty MCP config")
        return MCPConfig()

    servers_raw = data.get("mcp_servers", [])
    if not isinstance(servers_raw, list):
        logger.warning("'mcp_servers' must be a list; returning empty MCP config")
        return MCPConfig()

    servers: list[MCPServerConfig] = []
    for raw in servers_raw:
        cfg = _parse_server(raw)
        if cfg.name:  # drop skipped / unnamed entries
            servers.append(cfg)

    return MCPConfig(mcp_servers=servers)
