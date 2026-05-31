# Thermal Printer Middleware

> **A production-grade, async-first middleware service for Cashino thermal printers (KP-300 / 301H / 302)**  
> Built for the Aco technical assessment — engineered to handle the brutal realities of hardware I/O.

---

## Table of Contents

- [Overview](#-overview)
- [Architecture & Design Decisions](#-architecture--design-decisions)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [Authentication](#-authentication)
- [API Reference](#-api-reference)
- [Chaos Testing / Hardware Simulation](#-chaos-testing--hardware-simulation)
- [Logging](#-logging)
- [Bonus Features](#-bonus-features)
- [Running Tests](#-running-tests)

---

## Overview

Hardware peripherals are slow, unreliable, and blocking. This service exists to abstract all of that away.

The **Thermal Printer Middleware** acts as an intelligent broker between your application and a physical Cashino thermal printer. It accepts print jobs over HTTP, queues them safely, retries on transient errors, tracks every event with structured logs, and exposes a clean REST API — all without ever blocking the calling service.

**Key capabilities at a glance:**

- **Non-blocking async queue** — HTTP response is instant; printing happens in the background
- **Automatic retries** with exponential backoff for transient hardware faults
- **Idempotency** — the same job key will never print twice, even under duplicate requests
- **Persistence** — jobs survive server restarts; stale jobs are recovered automatically on boot
- **Token-based auth** on every endpoint
- **One-command Docker deployment**
- **Built-in simulator** for chaos testing without physical hardware

---

## Architecture & Design Decisions

> This section explains the *why* behind every non-obvious technical choice.

### 1. `asyncio.Queue` + Background Worker — not Redis, not Celery

The most common instinct for a job queue is to reach for Redis + Celery (or RQ). We deliberately didn't.

Thermal printer communication is **I/O-bound, not CPU-bound**. The bottleneck is a USB or TCP socket waiting for the printer to acknowledge data — an operation measured in tens to hundreds of milliseconds. This is exactly the problem Python's `asyncio` is designed to solve.

Introducing Redis as an external broker would mean:
- An extra process to monitor, secure, and keep in sync
- A new failure domain (what happens when Redis is down?)
- A deployment that requires a multi-container orchestration for what is fundamentally a single-device service

Instead, we use **FastAPI's lifespan context** to spin up a single `asyncio` background task that drains a bounded `asyncio.Queue(maxsize=100)`. The queue is in-process, zero-latency, and naturally backpressures: if 100 jobs are pending, the 101st HTTP call blocks at `await job_queue.put()` rather than silently overloading the printer. This is the correct primitive for this workload.

### 2. SQLite + SQLModel — not PostgreSQL, not in-memory

Print jobs carry commercial weight. A lost job means a customer who didn't get their receipt. Persistence is non-negotiable.

SQLite was chosen over PostgreSQL for these reasons:

- **Zero operational overhead** — no separate database server, no connection pooling config, no credentials to manage. The entire DB is a single file mounted via Docker volume.
- **Sufficient write throughput** — a thermal printer physically cannot accept jobs faster than SQLite can write them. WAL mode handles concurrent reads without issue.
- **SQLModel** (built on SQLAlchemy + Pydantic) gives us schema-as-code, typed queries, and automatic migrations without the ceremony of Alembic for a project of this scope.

The `idempotency_key` column has a `UNIQUE` constraint at the database level — not just in application logic. This is the correct layer for enforcing uniqueness guarantees.

### 3. Exponential Backoff Retry Strategy

Not all printer errors are equal. A `PAPER_JAM` requires a human; retrying is pointless. A `COMM_ERROR` or `TIMEOUT` may resolve itself within seconds as USB buffers flush.

The worker distinguishes **transient** errors (`COMM_ERROR`, `TIMEOUT`) from **terminal** ones (`PAPER_JAM`, `PAPER_OUT`, `COVER_OPEN`, `OVERHEAT`) and only retries the former. Backoff is computed as `retry_backoff_base ^ attempt` (configurable in `.env`), preventing thundering-herd behaviour when the printer recovers from a transient fault.

```
Attempt 1 → fail → wait 2s
Attempt 2 → fail → wait 4s
Attempt 3 → fail → FAILED (persisted with error_code + error_message)
```

### 4. Structured JSON Logging — Custom `AcoFormatFormatter`

Standard Python logging produces human-readable strings. Observability tooling (Datadog, Loki, CloudWatch) needs structured, machine-parseable events.

A custom `logging.Formatter` subclass emits every log entry as a single JSON line conforming to the exact schema specified in the Aco interview brief:

```json
{
  "ts":     "2026-05-31T14:23:01Z",
  "op":     "print_complete",
  "conn":   "usb",
  "jobId":  "a3f1c2d4-...",
  "status": "success"
}
```

Error events additionally carry an `error` object:

```json
{
  "ts":     "2026-05-31T14:23:05Z",
  "op":     "print_failed",
  "conn":   "usb",
  "jobId":  "b9e2f1...",
  "status": "error",
  "error":  { "code": "PAPER_OUT", "detail": "No paper detected" }
}
```

All logs are written simultaneously to `logs.json` on disk and to `stdout` (picked up by Docker).

---

## Project Structure

```
thermal-printer-service/
├── app/
│   ├── config.py               # Pydantic settings — all config via .env
│   ├── main.py                 # FastAPI app + lifespan (worker boot/shutdown)
│   ├── core/
│   │   ├── exceptions.py       # Domain exception types
│   │   ├── idempotency.py      # Idempotency key resolution
│   │   └── logger.py           # AcoFormatFormatter + get_logger()
│   ├── db/
│   │   ├── database.py         # SQLite engine + session factory
│   │   └── models.py           # Job, JobStatus, ContentType, PrinterError
│   ├── routers/
│   │   ├── printer.py          # /printer/* endpoints (auth-gated)
│   │   ├── logs.py             # /logs, /logs/export, /logs/prediction
│   │   └── health.py           # GET /health (unauthenticated)
│   ├── schemas/
│   │   └── schemas.py          # Pydantic request/response models
│   └── services/
│       ├── connection_manager.py   # USB / Ethernet / Simulation driver
│       ├── printer_service.py      # Job creation + idempotency check
│       ├── prediction_service.py   # Paper roll consumption model
│       └── queue_worker.py         # Background worker loop + retry logic
├── simulator/
│   └── printer_simulator.py    # Chaos injection triggers (FAIL_PAPER, FAIL_HEAT…)
├── tests/
│   └── test_api.py             # Integration tests (pytest + httpx)
├── ui/                         # Simple browser UI (served at /ui)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env                        # Local config (not committed)
```

---

## Getting Started

### Prerequisites

- Docker ≥ 20.x and Docker Compose ≥ 2.x  
  _That's it. No Python, no pip, no virtual env needed to run the service._

### One-Command Startup

```bash
git clone <repo-url> thermal-printer-service
cd thermal-printer-service
docker-compose up -d --build
```

The service is live at `http://localhost:3000`.

### Environment Variables

All configuration is driven by `.env`. Copy the example and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `CONNECTION_MODE` | `simulation` | `usb` · `ethernet` · `simulation` |
| `PRINTER_ETH_HOST` | `192.168.1.100` | Printer IP (Ethernet mode) |
| `PRINTER_ETH_PORT` | `9100` | RAW print port |
| `PRINTER_USB_VENDOR_ID` | `0x0519` | Cashino USB Vendor ID |
| `PRINTER_USB_PRODUCT_ID` | `0x0001` | Cashino USB Product ID |
| `MAX_RETRY_ATTEMPTS` | `3` | Max retry attempts per job |
| `RETRY_BACKOFF_BASE` | `2.0` | Exponential backoff base (seconds) |
| `JOB_TIMEOUT_SECONDS` | `30` | Max single-attempt duration |
| `DATABASE_URL` | `sqlite:///./thermal_printer.db` | SQLite path |
| `PAPER_ROLL_INITIAL_METERS` | `50.0` | Starting roll length for predictions |
| `AVG_PAPER_PER_PRINT_CM` | `10.0` | Average paper per job (cm) |
| `API_TOKEN` | _(required)_ | Token for `X-API-Key` header |

---

## Authentication

Every endpoint under `/printer` and `/logs` is protected by a static API token.

Pass the token in the `X-API-Key` request header:

```bash
curl -H "X-API-Key: aco-secret-token-2026" http://localhost:3000/printer/status
```

Requests missing or bearing an incorrect token receive `401 Unauthorized`.

The `GET /health` endpoint is intentionally unauthenticated — it is designed for Docker healthchecks and load-balancer probes.

---

## API Reference

### Connection

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/printer/connect` | Establish connection to the printer (`usb` / `ethernet` / `simulation`) |
| `GET` | `/printer/status` | Current printer state, queue depth, paper level, uptime |

**Connect request body:**
```json
{ "mode": "simulation" }
```

**Status response:**
```json
{
  "connected": true,
  "mode": "simulation",
  "status": "ready",
  "error_code": "none",
  "queue_depth": 0,
  "paper_remaining_pct": 87.4,
  "uptime_seconds": 142
}
```

---

### Print Jobs

All print endpoints return `202 Accepted` immediately. The job is queued and processed asynchronously.

| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/printer/print/text` | `PrintRequest` | Queue a plain-text print job |
| `POST` | `/printer/print/image` | `PrintRequest` | Queue a base64-encoded image job |
| `POST` | `/printer/print/qr` | `PrintRequest` | Queue a QR code generation + print job |
| `POST` | `/printer/reprint` | `ReprintRequest` | Re-queue a previously completed job |

**`PrintRequest` body:**
```json
{
  "content": "Thank you for your purchase!",
  "copies": 1,
  "idempotency_key": "order-9981-receipt"
}
```

> `idempotency_key` is optional but strongly recommended. If the same key is sent twice (e.g. due to a network retry), the second request returns the original job's status instead of printing twice.

**`PrintResponse` body:**
```json
{
  "job_id": "a3f1c2d4-89ab-4cde-b012-3456789abcde",
  "status": "queued",
  "message": "Text job queued. Use GET /logs to track progress.",
  "idempotency_key": "order-9981-receipt"
}
```

---

### Logs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/logs` | Paginated job history (JSON) |
| `GET` | `/logs/export` | Download full job history as CSV |
| `GET` | `/logs/prediction` | Estimated paper roll remaining & print count until empty |

**Prediction response:**
```json
{
  "paper_remaining_pct": 62.0,
  "estimated_jobs_remaining": 310,
  "estimated_paper_remaining_cm": 3100.0
}
```

---

## Chaos Testing / Hardware Simulation

Running without a physical printer? The simulation mode supports **deterministic fault injection** via magic keywords in the `content` field.

| Trigger keyword | Injected error | Description |
|---|---|---|
| `FAIL_PAPER` | `PAPER_OUT` | Simulates an empty paper roll |
| `FAIL_HEAT` | `OVERHEAT` | Simulates a thermal head overheat fault |
| `FAIL_JAM` | `PAPER_JAM` | Simulates a paper jam (non-retryable) |
| `FAIL_COMM` | `COMM_ERROR` | Simulates a USB/TCP communication failure (retryable) |

**Example — trigger a paper-out and observe retry behaviour:**
```bash
curl -X POST http://localhost:3000/printer/print/text \
  -H "X-API-Key: aco-secret-token-2026" \
  -H "Content-Type: application/json" \
  -d '{"content": "FAIL_PAPER please", "idempotency_key": "chaos-test-1"}'
```

Watch `logs.json` or `docker logs thermal-printer-service` to see the worker respond with `PAPER_OUT`, skip retries (non-transient), and mark the job `FAILED`.

Swap `FAIL_COMM` to see exponential backoff in action — three retry attempts logged with increasing wait intervals before final failure.

---

## Logging

All events are written in newline-delimited JSON to `logs.json` and mirrored to stdout.

**Log schema:**

| Field | Type | Description |
|---|---|---|
| `ts` | `string` | ISO 8601 UTC timestamp (`Z` suffix) |
| `op` | `string` | Operation name (`print_queued`, `print_failed`, etc.) |
| `conn` | `string` | Connection mode (`usb`, `ethernet`, `simulation`) |
| `jobId` | `string` | UUID of the relevant job (omitted for system events) |
| `status` | `string` | `info` or `error` |
| `error` | `object` | Present only on error events — `{ code, detail }` |

**Tail live logs:**
```bash
docker logs -f thermal-printer-service
# or
tail -f logs.json | python3 -m json.tool
```

---

## Bonus Features

### Paper Roll Prediction (`GET /logs/prediction`)

A lightweight consumption model calculates estimated remaining paper based on completed job history and the configured `AVG_PAPER_PER_PRINT_CM`. Useful for alerting before the roll runs out mid-shift.

### CSV Log Export (`GET /logs/export`)

Downloads the full job table as a `.csv` file — ready for importing into Excel, Grafana, or any BI tool. Headers include `job_id`, `status`, `content_type`, `attempt`, `error_code`, `created_at`, `completed_at`.

### Browser UI (`http://localhost:3000/ui`)

A minimal web interface for manually sending test print jobs, viewing queue depth, and reading recent log entries — without needing curl or Postman. Intended for quick demos and on-site debugging.

---

## Running Tests

Tests use **pytest** + **httpx** with the app running in `simulation` mode.

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run the test suite
pytest tests/ -v
```

Tests cover:
- Job submission and `202` response shape
- Idempotency: duplicate key returns original job, no double-print
- Reprint flow: new job ID referencing original
- Hardware error injection via chaos keywords
- `/status` endpoint field completeness
- `/logs` pagination
- Auth rejection on missing / invalid token

---

## Supported Printer Models

| Model | Interface | Status |
|---|---|---|
| Cashino KP-300 | USB | ✅ Supported |
| Cashino KP-301H | USB / Ethernet | ✅ Supported |
| Cashino KP-302 | USB / Ethernet | ✅ Supported |

Driver datasheet references are in the `docs/` directory (KP-300 User Manual V1.2, KP-301H V1.0).

---

## Docker Details

```yaml
# docker-compose.yml highlights
services:
  thermal-printer-service:
    ports:      ["3000:3000"]
    restart:    unless-stopped
    healthcheck:
      test:     ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout:  5s
      retries:  3
volumes:
  printer_data:   # SQLite file persisted across container restarts
```

The SQLite database is mounted as a named Docker volume (`printer_data`). Jobs survive `docker-compose restart` without any data loss.

---

