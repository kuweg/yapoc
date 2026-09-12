from .agents import router as agents_router
from .artifacts import router as artifacts_router
from .files import router as files_router
from .health import router as health_router
from .memory_graph import router as memory_graph_router
from .metrics import router as metrics_router
from .models import router as models_router
from .tasks import router as tasks_router
from .test_endpoint import router as test_endpoint_router
from .vault import router as vault_router
from .voice import router as voice_router
from .costs import router as costs_router
from .webhook import router as webhook_router
from .stale_tasks import router as stale_tasks_router
from .notification_trace import router as notification_trace_router
from .sessions import router as sessions_router
from .admin import router as admin_router
from .commands import router as commands_router
from .concilium import concilium_router
from .graph import router as graph_router
from .observability import router as observability_router
from .pptx import router as pptx_router
from .uploads import router as uploads_router
from .skills import router as skills_router
from .mcp import router as mcp_router, servers_router as mcp_servers_router
from .plugins import router as plugins_router
from .notes import router as notes_router
from .cron import router as cron_router
from .drive_oauth import router as drive_oauth_router
from .github import router as github_router
from .link_previews import router as link_previews_router
from .whiteboard import router as whiteboard_router

__all__ = [
    "artifacts_router",
    "health_router",
    "tasks_router",
    "agents_router",
    "metrics_router",
    "files_router",
    "memory_graph_router",
    "test_endpoint_router",
    "vault_router",
    "voice_router",
    "webhook_router",
    "costs_router",
    "models_router",
    "stale_tasks_router",
    "notification_trace_router",
    "sessions_router",
    "admin_router",
    "commands_router",
    "concilium_router",
    "graph_router",
    "observability_router",
    "pptx_router",
    "uploads_router",
    "skills_router",
    "mcp_router",
    "mcp_servers_router",
    "plugins_router",
    "notes_router",
    "cron_router",
    "drive_oauth_router",
    "github_router",
    "link_previews_router",
    "whiteboard_router",
]
