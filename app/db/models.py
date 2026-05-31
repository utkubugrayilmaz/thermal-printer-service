from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
import uuid


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    QR = "qr"


class PrinterError(str, Enum):
    NONE = "none"
    PAPER_OUT = "PAPER_OUT"
    PAPER_JAM = "PAPER_JAM"
    COVER_OPEN = "COVER_OPEN"
    OVERHEAT = "OVERHEAT"
    COMM_ERROR = "COMM_ERROR"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    TIMEOUT = "TIMEOUT"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    idempotency_key: Optional[str] = Field(default=None, index=True, unique=True)

    content_type: ContentType = Field(default=ContentType.TEXT)
    content: str = Field(default="")           # text body or base64 image
    copies: int = Field(default=1)

    status: JobStatus = Field(default=JobStatus.QUEUED, index=True)
    error_code: PrinterError = Field(default=PrinterError.NONE)
    error_message: Optional[str] = Field(default=None)

    attempt: int = Field(default=0)
    max_attempts: int = Field(default=3)

    original_job_id: Optional[str] = Field(default=None)
    is_reprint: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)

    estimated_paper_cm: float = Field(default=0.0)
