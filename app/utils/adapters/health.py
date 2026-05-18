"""Cheap, provider-aware credential probes used by `yapoc init` and `yapoc doctor`.

A single async entry point — ``check_provider`` — that returns ``(ok, message)``.
Each provider is hit with the lightest endpoint that still validates the key
(usually a model list). No completions are issued, so a probe costs nothing
and stays within free-tier limits.
"""

from __future__ import annotations

import httpx


_ANTHROPIC_VERSION = "2023-06-01"


async def check_provider(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """Validate a provider's credentials with a cheap network call.

    Returns ``(True, message)`` on success and ``(False, error)`` on any
    failure (missing key, network error, auth rejection). The message is
    user-facing — show it directly in the wizard / doctor.
    """
    provider = provider.lower().strip()
    try:
        if provider == "anthropic":
            return await _check_anthropic(api_key, timeout)
        if provider in ("openai", "codex"):
            return await _check_bearer(
                "https://api.openai.com/v1/models", api_key, timeout
            )
        if provider == "deepseek":
            return await _check_bearer(
                "https://api.deepseek.com/v1/models", api_key, timeout
            )
        if provider == "openrouter":
            return await _check_bearer(
                "https://openrouter.ai/api/v1/models", api_key, timeout
            )
        if provider == "google":
            return await _check_google(api_key, timeout)
        if provider == "ollama":
            return await _check_local(
                base_url or "http://localhost:11434", "/api/tags", timeout
            )
        if provider == "lmstudio":
            return await _check_local(
                base_url or "http://localhost:1234", "/v1/models", timeout, api_key
            )
    except httpx.TimeoutException:
        return False, f"{provider}: request timed out after {timeout:.0f}s"
    except httpx.RequestError as exc:
        return False, f"{provider}: network error — {exc}"
    except Exception as exc:
        return False, f"{provider}: unexpected error — {exc}"

    return False, f"unknown provider '{provider}'"


async def _check_anthropic(api_key: str | None, timeout: float) -> tuple[bool, str]:
    if not api_key:
        return False, "anthropic: ANTHROPIC_API_KEY is empty"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
            },
        )
    return _interpret(resp, "anthropic")


async def _check_bearer(
    url: str, api_key: str | None, timeout: float
) -> tuple[bool, str]:
    if not api_key:
        return False, f"{_provider_from_url(url)}: API key is empty"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url, headers={"Authorization": f"Bearer {api_key}"}
        )
    return _interpret(resp, _provider_from_url(url))


async def _check_google(api_key: str | None, timeout: float) -> tuple[bool, str]:
    if not api_key:
        return False, "google: GOOGLE_API_KEY (or GEMINI_API_KEY) is empty"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
    return _interpret(resp, "google")


async def _check_local(
    base_url: str, path: str, timeout: float, api_key: str | None = None
) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 200:
        return True, f"{base_url} reachable"
    return False, f"{base_url}: HTTP {resp.status_code}"


def _interpret(resp: httpx.Response, provider: str) -> tuple[bool, str]:
    if resp.status_code == 200:
        return True, f"{provider}: key validated"
    if resp.status_code in (401, 403):
        return False, f"{provider}: key rejected (HTTP {resp.status_code})"
    detail = resp.text[:200].strip().replace("\n", " ")
    return False, f"{provider}: HTTP {resp.status_code} — {detail}"


def _provider_from_url(url: str) -> str:
    if "openai.com" in url:
        return "openai"
    if "deepseek.com" in url:
        return "deepseek"
    if "openrouter.ai" in url:
        return "openrouter"
    return "provider"
