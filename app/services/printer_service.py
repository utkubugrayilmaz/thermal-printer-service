from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Session, select
from app.db.models import Job, JobStatus, PrinterError, ContentType
from app.schemas.schemas import PrintRequest, ReprintRequest
from app.core.idempotency import check_idempotency
from app.core.exceptions import JobNotFoundError, PrinterNotConnectedError
from app.core.logger import get_logger
from app.services.connection_manager import connection_manager
from app.services.queue_worker import enqueue
from app.config import settings

logger = get_logger("printer_service")

_AVG_CM_PER_PRINT = settings.avg_paper_per_print_cm


async def submit_print_job(session: Session, req: PrintRequest) -> Job:

    if not connection_manager.is_connected():
        raise PrinterNotConnectedError()

    check_idempotency(session, req.idempotency_key)

    lines = len(req.content.splitlines()) + 3
    estimated_cm = (lines * 0.33) * req.copies

    job = Job(
        content=req.content,
        content_type=req.content_type,
        copies=req.copies,
        idempotency_key=req.idempotency_key,
        max_attempts=settings.max_retry_attempts,
        estimated_paper_cm=estimated_cm,
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    logger.info(
        "Print job submitted",
        extra={
            "job_id": job.id,
            "content_type": job.content_type,
            "copies": job.copies,
            "idempotency_key": req.idempotency_key,
        },
    )

    await enqueue(job.id)
    return job


async def submit_reprint(session: Session, req: ReprintRequest) -> Job:

    if not connection_manager.is_connected():
        raise PrinterNotConnectedError()

    original = session.get(Job, req.job_id)
    if not original:
        raise JobNotFoundError(req.job_id)

    reprint = Job(
        content=original.content,
        content_type=original.content_type,
        copies=original.copies,
        max_attempts=settings.max_retry_attempts,
        estimated_paper_cm=original.estimated_paper_cm,
        status=JobStatus.QUEUED,
        is_reprint=True,
        original_job_id=original.id,
    )
    session.add(reprint)
    session.commit()
    session.refresh(reprint)

    logger.info(
        "Reprint submitted",
        extra={"new_job_id": reprint.id, "original_job_id": original.id},
    )

    await enqueue(reprint.id)
    return reprint


def get_jobs(
    session: Session,
    status: Optional[JobStatus] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Job], int]:
    query = select(Job)
    if status:
        query = query.where(Job.status == status)
    query = query.order_by(Job.created_at.desc())

    total = len(session.exec(query).all())
    offset = (page - 1) * page_size
    jobs = session.exec(query.offset(offset).limit(page_size)).all()
    return list(jobs), total
