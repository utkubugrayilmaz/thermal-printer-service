"""
API Integration Tests
---------------------
Uses FastAPI's TestClient (sync) so no real printer is needed.
Run: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite://"


@pytest.fixture(scope="session", autouse=True)
def override_db():
    """Patch the database engine to use an in-memory SQLite instance."""
    from app.db import database
    import app.services.queue_worker as qw

    test_engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    # Patch both the database module AND the queue worker (which imports engine directly)
    database.engine = test_engine
    qw.engine = test_engine

    def get_test_session():
        with Session(test_engine) as session:
            yield session

    database.get_session = get_test_session
    yield


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Health ──────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert body["db_ok"] is True


# ── Connect ─────────────────────────────────────────────────────────────────

def test_connect_simulation(client):
    r = client.post("/printer/connect", json={"mode": "simulation"})
    assert r.status_code == 200
    assert r.json()["connected"] is True


# ── Status ──────────────────────────────────────────────────────────────────

def test_status(client):
    r = client.get("/printer/status")
    assert r.status_code == 200
    body = r.json()
    assert "connected" in body
    assert "queue_depth" in body


# ── Print ────────────────────────────────────────────────────────────────────

def test_print_text(client):
    r = client.post("/printer/print", json={
        "content": "Hello, ACO!",
        "content_type": "text",
        "copies": 1,
    })
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_print_empty_content(client):
    r = client.post("/printer/print", json={"content": "   "})
    assert r.status_code == 422


def test_print_idempotency(client):
    payload = {"content": "Idempotent job", "idempotency_key": "test-key-001"}
    r1 = client.post("/printer/print", json=payload)
    r2 = client.post("/printer/print", json=payload)
    assert r1.status_code == 202
    assert r2.status_code == 409  # conflict


# ── Reprint ──────────────────────────────────────────────────────────────────

def test_reprint_existing_job(client):
    r = client.post("/printer/print", json={"content": "Reprint me"})
    job_id = r.json()["job_id"]
    rr = client.post("/printer/reprint", json={"job_id": job_id})
    assert rr.status_code == 202
    assert rr.json()["original_job_id"] == job_id


def test_reprint_nonexistent_job(client):
    r = client.post("/printer/reprint", json={"job_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404


# ── Logs ─────────────────────────────────────────────────────────────────────

def test_logs_list(client):
    r = client.get("/logs")
    assert r.status_code == 200
    body = r.json()
    assert "jobs" in body
    assert "total" in body


def test_logs_export_csv(client):
    r = client.get("/logs/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "id" in r.text  # CSV header


def test_logs_prediction(client):
    r = client.get("/logs/prediction")
    assert r.status_code == 200
    body = r.json()
    assert "paper_remaining_cm" in body
    assert "estimated_prints_left" in body


# ── QR print ─────────────────────────────────────────────────────────────────

def test_print_qr(client):
    r = client.post("/printer/print", json={
        "content": "https://aco-recycling.com",
        "content_type": "qr",
    })
    assert r.status_code == 202
