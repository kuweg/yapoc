from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── API keys ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    # Google Gemini — accepts GOOGLE_API_KEY or GEMINI_API_KEY
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    lmstudio_api_key: str = ""  # usually unused; LM Studio runs keyless by default

    # ── Local / self-hosted endpoints ───────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    lmstudio_base_url: str = "http://localhost:1234"

    # ── Fallback routing ─────────────────────────────────────────────────────
    default_n_fallbacks_models: int = 1  # number of fallback models per agent

    # ── Default LLM ──────────────────────────────────────────────────────────
    default_adapter: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    default_temperature: float = 0.7
    enable_thinking: bool = False
    thinking_budget_tokens: int = 8000  # must be < max_tokens (default 8096)

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Runner defaults ──────────────────────────────────────────────────────
    max_turns: int = 20
    task_timeout: int = 300

    # ── Safety ────────────────────────────────────────────────────────────
    max_shell_timeout: int = 120  # hard cap on shell command timeout (seconds)
    safety_mode: str = "interactive"  # "interactive" | "auto_approve" | "strict"

    # ── Agent processes ─────────────────────────────────────────────────
    agent_idle_timeout: int = 300  # seconds before idle agent self-terminates
    agent_spawn_timeout: int = 15  # seconds to wait for spawn confirmation
    runner_poll_interval: int = 30  # TASK.MD poll fallback interval (seconds)
    # Hard cap on live sub-agent processes to prevent runaway fan-out
    # (prompt injection / model confusion can otherwise spawn many at once).
    # Counts STATUS.json entries in state=idle|running|spawning.
    max_concurrent_agents: int = 10

    # ── Context management ─────────────────────────────────────────────
    context_compact_threshold: float = (
        0.85  # fraction of context window before auto-compact
    )
    context_compact_model: str = (
        "claude-haiku-4-5-20251001"  # cheap model for compaction
    )

    # ── Cost governance ────────────────────────────────────────────────
    budget_per_task_usd: float = 0.0     # 0 = no limit; hard pause when exceeded
    budget_per_agent_usd: float = 0.0    # 0 = no limit; per-agent lifetime cap
    cost_runaway_multiplier: float = 5.0 # pause if agent cost > multiplier x median agent cost

    # ── Logging / health ──────────────────────────────────────────────
    log_max_size_kb: int = 512  # OUTPUT.MD size cap before rotation
    log_level: str = "INFO"          # Python log level: DEBUG|INFO|WARNING|ERROR  (env: LOG_LEVEL)
    log_file: str = ""               # empty = stderr only; path = rotating file   (env: LOG_FILE)
    log_json: bool = False           # True → JSON-Lines output                    (env: LOG_JSON)
    log_agent_activity: bool = True  # master switch for agent event logging        (env: LOG_AGENT_ACTIVITY)
    doctor_interval_minutes: int = 5  # Doctor cron frequency
    cron_interval_minutes: int = 10  # Cron agent trigger frequency
    health_log_retention_days: int = 7  # HEALTH.MD entries older than this are pruned
    model_manager_interval_hours: int = 24  # Model Manager audit frequency

    # ── Embedding / indexer ───────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_index_interval_minutes: int = 10

    # ── Paths ────────────────────────────────────────────────────────────────
    @property
    def project_root(self) -> Path:
        return Path(__file__).parent.parent.parent

    @property
    def agents_dir(self) -> Path:
        return self.project_root / "app" / "agents"

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
