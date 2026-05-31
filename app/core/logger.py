import logging
import json
import sys
from datetime import datetime, timezone


class AcoFormatFormatter(logging.Formatter):

    def format(self, record):
        log_record = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        log_record["op"] = getattr(record, "op", getattr(record, "event", "system_log"))

        log_record["conn"] = getattr(record, "conn", getattr(record, "mode", "usb"))

        if hasattr(record, "job_id"):
            log_record["jobId"] = str(record.job_id)
        elif hasattr(record, "jobId"):
            log_record["jobId"] = str(record.jobId)

        if hasattr(record, "status"):
            log_record["status"] = record.status
        else:
            log_record["status"] = "info" if record.levelno < logging.ERROR else "error"

        error_code = getattr(record, "error_code", None)
        if error_code and error_code != "none":
            log_record["status"] = "error"
            log_record["error"] = {
                "code": error_code,
                "detail": getattr(record, "error_detail", getattr(record, "error_message", record.getMessage()))
            }

        if "jobId" not in log_record and log_record["op"] == "system_log":
            log_record["message"] = record.getMessage()
            log_record["level"] = record.levelname

        return json.dumps(log_record)


def get_logger(name: str):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = AcoFormatFormatter()

        file_handler = logging.FileHandler("logs.json", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

logger = get_logger("thermal_printer")