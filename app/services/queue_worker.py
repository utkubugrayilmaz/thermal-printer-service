import asyncio
import math
from datetime import datetime, timezone
from sqlmodel import Session
from app.config import settings
from app.db.database import engine
from app.db.models import Job, JobStatus, PrinterError
from app.services.connection_manager import connection_manager
from app.core.logger import get_logger

logger = get_logger("queue_worker")

job_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)


async def enqueue(job_id: str) -> None:
    await job_queue.put(job_id)
    logger.info("Job enqueued", extra={"job_id": job_id, "queue_depth": job_queue.qsize()})


async def worker_loop() -> None:
    logger.info("Queue worker started")
    await _recover_stale_jobs()

    while True:
        job_id = await job_queue.get()
        try:
            await _process_job(job_id)
        except asyncio.CancelledError:
            logger.info("Queue worker shutting down")
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in worker loop",
                extra={"job_id": job_id, "error": str(exc)},
            )
        finally:
            job_queue.task_done()


async def _process_job(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            logger.warning("Job not found, skipping", extra={"job_id": job_id})
            return

        if job.status not in (JobStatus.QUEUED, JobStatus.PROCESSING):
            return


        job.status = JobStatus.PROCESSING
        job.attempt += 1
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

    logger.info(
        "Processing job",
        extra={"job_id": job_id, "attempt": job.attempt, "content_type": job.content_type},
    )

    if not connection_manager.is_connected():
        await _fail_job(job_id, PrinterError.COMM_ERROR, "Printer not connected")
        return

    hw_error = await connection_manager.check_hardware_status()
    if hw_error:
        await _fail_job(job_id, hw_error, f"Hardware error: {hw_error}")
        return

    last_error: str = ""
    for attempt in range(1, job.max_attempts + 1):
        try:
            await connection_manager.print(
                content=job.content,
                content_type=job.content_type,
                copies=job.copies,
            )
            await _succeed_job(job_id)
            return

        except RuntimeError as exc:
            error_code = str(exc)
            last_error = error_code

            is_transient = error_code in (
                PrinterError.COMM_ERROR,
                PrinterError.TIMEOUT,
            )

            logger.warning(
                "Print attempt failed",
                extra={
                    "job_id": job_id,
                    "attempt": attempt,
                    "max_attempts": job.max_attempts,
                    "error_code": error_code,
                    "will_retry": is_transient and attempt < job.max_attempts,
                },
            )

            if not is_transient or attempt == job.max_attempts:
                await _fail_job(
                    job_id,
                    error_code if error_code in PrinterError._value2member_map_ else PrinterError.COMM_ERROR,
                    f"Failed after {attempt} attempt(s): {error_code}",
                )
                return

            backoff = settings.retry_backoff_base ** attempt
            logger.info(
                "Retrying after backoff",
                extra={"job_id": job_id, "backoff_seconds": backoff},
            )
            await asyncio.sleep(backoff)

    await _fail_job(job_id, PrinterError.COMM_ERROR, f"Exhausted retries: {last_error}")


async def _succeed_job(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job:
            now = datetime.now(timezone.utc)
            job.status = JobStatus.SUCCESS
            job.error_code = PrinterError.NONE
            job.updated_at = now
            job.completed_at = now
            session.add(job)
            session.commit()
    logger.info("Job succeeded", extra={"job_id": job_id})


async def _fail_job(job_id: str, error_code, message: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job:
            now = datetime.now(timezone.utc)
            job.status = JobStatus.FAILED
            job.error_code = error_code if isinstance(error_code, PrinterError) else PrinterError.COMM_ERROR
            job.error_message = message
            job.updated_at = now
            job.completed_at = now
            session.add(job)
            session.commit()
    logger.error("Job failed", extra={"job_id": job_id, "error": message})


async def _recover_stale_jobs() -> None:
    from sqlmodel import select
    with Session(engine) as session:
        stale = session.exec(
            select(Job).where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING])  # type: ignore
            )
        ).all()

    for job in stale:
        logger.info("Recovering stale job", extra={"job_id": job.id})
        await job_queue.put(job.id)
