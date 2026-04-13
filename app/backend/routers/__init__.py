from .agents import router as agents_router
from .files import router as files_router
from .health import router as health_router
from .memory_graph import router as memory_graph_router
from .metrics import router as metrics_router
from .tasks import router as tasks_router
from .test_endpoint import router as test_endpoint_router
from .tickets import router as tickets_router
from .vault import router as vault_router

__all__ = ["health_router", "tasks_router", "agents_router", "metrics_router", "tickets_router", "files_router", "memory_graph_router", "test_endpoint_router", "vault_router"]
