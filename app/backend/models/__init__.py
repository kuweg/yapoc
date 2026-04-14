from pydantic import BaseModel


class TaskRequest(BaseModel):
    task: str
    history: list[dict] | None = None
    source: str | None = None  # "cli", "ui", "notification"


class TaskResponse(BaseModel):
    status: str
    response: str


class ApprovalRequest(BaseModel):
    approved: bool


class AgentStatus(BaseModel):
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
