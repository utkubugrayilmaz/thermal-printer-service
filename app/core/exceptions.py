from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from app.db.models import PrinterError


class PrinterNotConnectedError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=503,
            detail={
                "error_code": PrinterError.COMM_ERROR,
                "message": "Printer is not connected. Call POST /connect first.",
            },
        )


class JobNotFoundError(HTTPException):
    def __init__(self, job_id: str):
        super().__init__(
            status_code=404,
            detail={
                "error_code": "JOB_NOT_FOUND",
                "message": f"Job '{job_id}' not found.",
            },
        )


class IdempotencyConflictError(HTTPException):
    def __init__(self, job_id: str):
        super().__init__(
            status_code=409,
            detail={
                "error_code": "IDEMPOTENCY_CONFLICT",
                "message": "A job with this idempotency_key already exists.",
                "existing_job_id": job_id,
            },
        )


class PrinterBusyError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=429,
            detail={
                "error_code": "PRINTER_BUSY",
                "message": "Print queue is full. Try again shortly.",
            },
        )


class PrinterHardwareError(HTTPException):
    def __init__(self, error_code: PrinterError, detail: str = ""):
        super().__init__(
            status_code=422,
            detail={
                "error_code": error_code,
                "message": detail or f"Printer hardware error: {error_code}",
            },
        )


async def printer_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )
