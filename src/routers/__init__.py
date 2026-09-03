from .auth import router as auth_router
from .services import router as services_router
from .logs import router as logs_router
from .system import router as system_router

__all__ = [
    "auth_router",
    "services_router",
    "logs_router",
    "system_router"
]
