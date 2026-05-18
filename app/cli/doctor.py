"""Preflight check for YAPOC — `poetry run yapoc doctor`.

Non-interactive, read-only. Prints a green/red checklist and exits 0 on
all-green, 1 if anything failed. Safe to call from CI or `install.sh`.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

import httpx
from rich.console import Console
from rich.table import Table

from app.config import settings
from app.utils.adapters.health import check_provider


console = Console()


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""

    @property
    def mark(self) -> str:
        return "[green]ok[/green]" if self.ok else "[red]fail[/red]"


@dataclass
class PreflightSummary:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)


def run_preflight() -> int:
    """Run every check and render the summary. Returns shell exit code."""
    summary = PreflightSummary()
    summary.results.append(_check_python())
    summary.results.append(_check_redis())

    api_check, active_provider = _check_api_keys()
    summary.results.append(api_check)
    if active_provider:
        summary.results.append(_check_provider_live(active_provider))

    summary.results.append(_check_backend())
    summary.results.append(_check_projects_dir())

    _render(summary)
    return 0 if summary.all_ok else 1


# ── individual checks ───────────────────────────────────────────────────────


def _check_python() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return CheckResult(
        name="Python >= 3.12",
        ok=ok,
        detail=f"{v.major}.{v.minor}.{v.micro}",
        fix="Install Python 3.12+ (e.g. `pyenv install 3.12`)" if not ok else "",
    )


def _check_redis() -> CheckResult:
    try:
        import redis.asyncio as redis_async

        async def _ping() -> bool:
            client = redis_async.Redis.from_url(settings.redis_url, socket_timeout=2.0)
            try:
                return bool(await client.ping())
            finally:
                await client.aclose()

        ok = asyncio.run(_ping())
        return CheckResult(
            name="Redis reachable",
            ok=ok,
            detail=settings.redis_url,
            fix="Run `redis-server` or `make start-redis`" if not ok else "",
        )
    except Exception as exc:
        return CheckResult(
            name="Redis reachable",
            ok=False,
            detail=f"{settings.redis_url} — {exc}",
            fix="Run `redis-server` or `make start-redis`",
        )


def _check_api_keys() -> tuple[CheckResult, str]:
    """Returns (result, active_provider). Active provider is the one whose
    key is set and matches ``settings.default_adapter``; otherwise the first
    set key. Empty string means no probe will follow."""
    keys_by_provider: dict[str, str] = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "deepseek": settings.deepseek_api_key,
        "openrouter": settings.openrouter_api_key,
        "google": settings.google_api_key,
    }
    set_providers = [p for p, v in keys_by_provider.items() if v]

    active = ""
    if keys_by_provider.get(settings.default_adapter):
        active = settings.default_adapter
    elif set_providers:
        active = set_providers[0]

    if set_providers:
        return (
            CheckResult(
                name="API key configured",
                ok=True,
                detail=", ".join(set_providers),
            ),
            active,
        )

    return (
        CheckResult(
            name="API key configured",
            ok=False,
            detail="no provider keys in .env",
            fix="Run `poetry run yapoc init`",
        ),
        "",
    )


def _check_provider_live(provider: str) -> CheckResult:
    key_attr: dict[str, str] = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "codex": settings.openai_api_key,
        "deepseek": settings.deepseek_api_key,
        "openrouter": settings.openrouter_api_key,
        "google": settings.google_api_key,
        "lmstudio": settings.lmstudio_api_key,
    }
    base_url_attr: dict[str, str] = {
        "ollama": settings.ollama_base_url,
        "lmstudio": settings.lmstudio_base_url,
    }
    ok, msg = asyncio.run(
        check_provider(
            provider,
            api_key=key_attr.get(provider, ""),
            base_url=base_url_attr.get(provider, ""),
        )
    )
    return CheckResult(
        name=f"{provider} probe",
        ok=ok,
        detail=msg,
        fix="Re-run `yapoc init` to update credentials" if not ok else "",
    )


def _check_backend() -> CheckResult:
    url = f"{settings.base_url}/health"
    try:
        resp = httpx.get(url, timeout=2.0)
    except httpx.ConnectError:
        return CheckResult(
            name="Backend port",
            ok=True,
            detail=f"{settings.base_url} free — ready for `yapoc start`",
        )
    except Exception as exc:
        return CheckResult(name="Backend port", ok=False, detail=str(exc))

    if resp.status_code == 200:
        return CheckResult(
            name="Backend port",
            ok=True,
            detail=f"already up at {settings.base_url}",
        )
    return CheckResult(
        name="Backend port",
        ok=False,
        detail=f"HTTP {resp.status_code} at {url}",
        fix="Stop the process holding the port",
    )


def _check_projects_dir() -> CheckResult:
    p = settings.project_root / "app" / "projects"
    ok = p.exists() and p.is_dir()
    return CheckResult(
        name="app/projects/",
        ok=ok,
        detail=str(p.relative_to(settings.project_root)),
        fix="Run `poetry run yapoc init` (auto-creates the dir)" if not ok else "",
    )


# ── rendering ───────────────────────────────────────────────────────────────


def _render(summary: PreflightSummary) -> None:
    table = Table(title="YAPOC preflight", title_style="bold yellow")
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")
    table.add_column("Fix hint", overflow="fold", style="dim")
    for r in summary.results:
        table.add_row(r.name, r.mark, r.detail, r.fix)
    console.print(table)

    total = len(summary.results)
    if summary.all_ok:
        console.print(f"\n[green]all {total} checks passed[/green]\n")
    else:
        console.print(
            f"\n[red]{total - summary.passed}/{total} checks failed[/red] — "
            "fix the red rows above and re-run `yapoc doctor`\n"
        )
