import csv
import io
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.db.database import get_session
from app.db.models import JobStatus
from app.schemas.schemas import LogsResponse, JobLog, PredictionResponse
from app.services.printer_service import get_jobs
from app.services.prediction_service import get_prediction

# Printer router'ında yazdığımız yetkilendirme fonksiyonunu içeri aktarıyoruz
from app.routers.printer import verify_token

# Router'a yetkilendirmeyi (dependencies) bağlıyoruz.
# Artık bu dosyadaki listeleme, export ve prediction uçlarına tokensız erişilemez.
router = APIRouter(prefix="/logs", tags=["Logs"], dependencies=[Depends(verify_token)])


@router.get("", response_model=LogsResponse)
def list_logs(
    status: Optional[JobStatus] = Query(default=None, description="Filter by job status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    jobs, total = get_jobs(session, status=status, page=page, page_size=page_size)
    return LogsResponse(
        total=total,
        page=page,
        page_size=page_size,
        jobs=[JobLog.model_validate(j) for j in jobs],
    )


@router.get("/export", response_class=StreamingResponse)
def export_logs_csv(
    status: Optional[JobStatus] = Query(default=None),
    session: Session = Depends(get_session),
):
    jobs, _ = get_jobs(session, status=status, page=1, page_size=10_000)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "content_type", "status", "error_code", "error_message",
            "attempt", "copies", "is_reprint", "original_job_id",
            "created_at", "updated_at", "completed_at", "estimated_paper_cm",
        ],
    )
    writer.writeheader()
    for job in jobs:
        writer.writerow({
            "id": job.id,
            "content_type": job.content_type,
            "status": job.status,
            "error_code": job.error_code,
            "error_message": job.error_message or "",
            "attempt": job.attempt,
            "copies": job.copies,
            "is_reprint": job.is_reprint,
            "original_job_id": job.original_job_id or "",
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else "",
            "estimated_paper_cm": job.estimated_paper_cm,
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=print_jobs.csv"},
    )


@router.get("/prediction", response_model=PredictionResponse)
def paper_prediction(session: Session = Depends(get_session)):
    return get_prediction(session)