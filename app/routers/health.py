import time
from fastapi import APIRouter
from sqlmodel import text
from app.db.database import engine
from app.schemas.schemas import HealthResponse
from app.services.connection_manager import connection_manager
from app.services.queue_worker import job_queue
from app.config import settings

router = APIRouter(tags=["Health"])
_start = time.monotonic()


@router.get("/health", response_model=HealthResponse)
def health():
    """Liveness + readiness check."""
    # Quick DB ping
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    connected = connection_manager.is_connected()
    overall = "ok" if (connected and db_ok) else ("degraded" if db_ok else "down")

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        printer_connected=connected,
        queue_depth=job_queue.qsize(),
        db_ok=db_ok,
        uptime_seconds=round(time.monotonic() - _start, 1),
    )
