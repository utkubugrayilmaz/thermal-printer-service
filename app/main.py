import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import create_db_and_tables
from app.services.queue_worker import worker_loop
from app.services.connection_manager import connection_manager
from app.routers import printer_router, logs_router, health_router
from app.core.logger import logger
from app.core.exceptions import printer_exception_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info(
        "Starting up",
        extra={"app": settings.app_name, "version": settings.app_version},
    )
    create_db_and_tables()

    # Auto-connect in simulation mode on startup
    if not connection_manager.is_connected():
        try:
            await connection_manager.connect()
        except Exception as exc:
            logger.warning("Auto-connect failed", extra={"error": str(exc)})

    # Launch background queue worker
    worker_task = asyncio.create_task(worker_loop(), name="queue_worker")

    yield  # ← app is running

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("Shutting down")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await connection_manager.disconnect()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Thermal printer management service with async job queue, "
        "retry/backoff, idempotency, and paper prediction."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handlers ─────────────────────────────────────────────────────
app.add_exception_handler(HTTPException, printer_exception_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", extra={"error": str(exc), "path": str(request.url)})
    return JSONResponse(
        status_code=500,
        content={"error": {"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


# ── Routers ────────────────────────────────────────────────────────────────
app.include_router(printer_router)
app.include_router(logs_router)
app.include_router(health_router)

# ── Static UI ──────────────────────────────────────────────────────────────
try:
    app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")
except RuntimeError:
    pass  # ui folder may not exist in some deploy envs


@app.get("/", include_in_schema=False)
async def root():
    return {"service": settings.app_name, "version": settings.app_version, "docs": "/docs", "ui": "/ui"}
