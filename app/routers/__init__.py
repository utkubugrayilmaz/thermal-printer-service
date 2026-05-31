from .printer import router as printer_router
from .logs import router as logs_router
from .health import router as health_router

__all__ = ["printer_router", "logs_router", "health_router"]
