from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from app.db.models import JobStatus, ContentType, PrinterError
from app.config import ConnectionMode


class ConnectRequest(BaseModel):
    mode: ConnectionMode = ConnectionMode.SIMULATION
    host: Optional[str] = None
    port: Optional[int] = None
    vendor_id: Optional[str] = None
    product_id: Optional[str] = None


class ConnectResponse(BaseModel):
    connected: bool
    mode: ConnectionMode
    message: str


class PrintRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10_000)
    content_type: ContentType = ContentType.TEXT
    copies: int = Field(default=1, ge=1, le=20)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content cannot be blank")
        return v


class PrintResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
    idempotency_key: Optional[str] = None


class ReprintRequest(BaseModel):
    job_id: str = Field(..., min_length=36, max_length=36)


class ReprintResponse(BaseModel):
    new_job_id: str
    original_job_id: str
    status: JobStatus
    message: str


class PrinterStatusResponse(BaseModel):
    connected: bool
    mode: ConnectionMode
    status: str                  # ready | busy | error | offline
    error_code: PrinterError
    queue_depth: int
    paper_remaining_pct: Optional[float] = None
    uptime_seconds: float


class JobLog(BaseModel):
    id: str
    content_type: ContentType
    status: JobStatus
    error_code: PrinterError
    error_message: Optional[str]
    attempt: int
    is_reprint: bool
    original_job_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    estimated_paper_cm: float

    model_config = {"from_attributes": True}


class LogsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    jobs: List[JobLog]

class HealthResponse(BaseModel):
    status: str          # ok | degraded | down
    version: str
    printer_connected: bool
    queue_depth: int
    db_ok: bool
    uptime_seconds: float


class PredictionResponse(BaseModel):
    paper_remaining_cm: float
    paper_remaining_pct: float
    estimated_prints_left: int
    roll_eta_message: str
    low_paper_warning: bool
