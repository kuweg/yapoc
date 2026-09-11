from pydantic import BaseModel, Field

from app.backend.models.voice import TTSRequest, TTSVoice, TTSVoicesResponse, STTRequest, STTResponse  # noqa: F401


class TaskRequest(BaseModel):
    task: str
    task_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    after_seq: int = Field(default=0, ge=0)
    history: list[dict] | None = None
    source: str | None = None  # "cli", "ui", "notification"
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    attachments: list[str] | None = None  # uploaded attachment IDs (owner-scoped)
    note_ids: list[str] = Field(default_factory=list, max_length=12)


class TaskResponse(BaseModel):
    status: str
    response: str


class AgentStatus(BaseModel):
    office_role: str = ""
    runtime_state: str = "unknown"
    name: str
    status: str
    model: str
    has_task: bool
    memory_entries: int
    health_errors: int
    process_state: str = ""
    pid: int | None = None
    task_summary: str = ""
    # Extended fields for the new dashboard
    adapter: str = ""
    state: str = ""          # running | idle | done | error (from STATUS.json)
    health: str = "ok"       # ok | warning | critical
    started_at: str | None = None
    updated_at: str | None = None
    idle_since: str | None = None
    last_memory_entry: str | None = None
    tokens_per_second: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    is_infrastructure: bool = False


class HealthLogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    context: str | None = None


class TaskDetail(BaseModel):
    status: str = ""
    assigned_by: str = ""
    assigned_at: str = ""
    completed_at: str | None = None
    task_text: str = ""
    result_text: str | None = None
    error_text: str | None = None


class AgentDetail(AgentStatus):
    task: TaskDetail | None = None
    health_log: list[HealthLogEntry] = []
    memory_log: list[str] = []
    uptime_seconds: int | None = None
