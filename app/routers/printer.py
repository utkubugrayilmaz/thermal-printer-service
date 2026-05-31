from fastapi import APIRouter, Depends, BackgroundTasks
from sqlmodel import Session
from app.db.database import get_session
from app.db.models import PrinterError
from app.schemas.schemas import (
    ConnectRequest, ConnectResponse,
    PrintRequest, PrintResponse,
    ReprintRequest, ReprintResponse,
    PrinterStatusResponse,
)
from app.services.connection_manager import connection_manager
from app.services.printer_service import submit_print_job, submit_reprint
from app.services.queue_worker import job_queue
from app.config import ConnectionMode
import time

router = APIRouter(prefix="/printer", tags=["Printer"])
_start_time = time.monotonic()


@router.post("/connect", response_model=ConnectResponse, status_code=200)
async def connect(req: ConnectRequest):
    try:
        await connection_manager.connect(mode=req.mode)
    except RuntimeError as exc:
        return ConnectResponse(
            connected=False,
            mode=req.mode,
            message=f"Connection failed: {exc}",
        )
    return ConnectResponse(
        connected=True,
        mode=connection_manager.mode,
        message=f"Connected in {connection_manager.mode} mode.",
    )


@router.post("/print", response_model=PrintResponse, status_code=202)
async def print_job(req: PrintRequest, session: Session = Depends(get_session)):
    job = await submit_print_job(session, req)
    return PrintResponse(
        job_id=job.id,
        status=job.status,
        message="Job queued. Use GET /logs to track progress.",
        idempotency_key=req.idempotency_key,
    )


@router.post("/reprint", response_model=ReprintResponse, status_code=202)
async def reprint(req: ReprintRequest, session: Session = Depends(get_session)):
    reprint_job = await submit_reprint(session, req)
    return ReprintResponse(
        new_job_id=reprint_job.id,
        original_job_id=req.job_id,
        status=reprint_job.status,
        message="Reprint job queued.",
    )


@router.get("/status", response_model=PrinterStatusResponse)
async def status():
    connected = connection_manager.is_connected()
    hw_error = await connection_manager.check_hardware_status() if connected else None

    if not connected:
        printer_status = "offline"
    elif hw_error:
        printer_status = "error"
    elif job_queue.qsize() > 0:
        printer_status = "busy"
    else:
        printer_status = "ready"

    paper_cm, paper_pct = connection_manager.get_paper_info()

    return PrinterStatusResponse(
        connected=connected,
        mode=connection_manager.mode,
        status=printer_status,
        error_code=hw_error or PrinterError.NONE,
        queue_depth=job_queue.qsize(),
        paper_remaining_pct=paper_pct if paper_pct >= 0 else None,
        uptime_seconds=connection_manager.uptime_seconds,
    )
