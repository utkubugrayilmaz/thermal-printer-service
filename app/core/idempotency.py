from typing import Optional
from sqlmodel import Session, select
from app.db.models import Job
from app.core.exceptions import IdempotencyConflictError


def check_idempotency(session: Session, key: Optional[str]) -> None:
    """
    Raises IdempotencyConflictError if a job with this key already exists.
    No-op if key is None.
    """
    if not key:
        return

    existing = session.exec(
        select(Job).where(Job.idempotency_key == key)
    ).first()

    if existing:
        raise IdempotencyConflictError(job_id=existing.id)
