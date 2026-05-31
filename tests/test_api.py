import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool

TEST_DB_URL = "sqlite://"
TEST_TOKEN = "aco_secret_token_1919"
AUTH = {"X-API-Key": TEST_TOKEN}


@pytest.fixture(scope="session", autouse=True)
def override_db():
    from app.db import database
    import app.services.queue_worker as qw

    test_engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

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


# ── Health (auth gerektirmez) ─────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert body["db_ok"] is True


# ── Auth guard ────────────────────────────────────────────────────────────────

def test_auth_missing_token(client):
    r = client.get("/printer/status")
    assert r.status_code == 401


def test_auth_wrong_token(client):
    r = client.get("/printer/status", headers={"X-API-Key": "wrong-token"})
    assert r.status_code == 401


# ── Bağlantı ─────────────────────────────────────────────────────────────────

def test_connect_simulation(client):
    r = client.post("/printer/connect", json={"mode": "simulation"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["connected"] is True


def test_status(client):
    r = client.get("/printer/status", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "connected" in body
    assert "queue_depth" in body


# ── Baskı işleri ──────────────────────────────────────────────────────────────

def test_print_text(client):
    r = client.post("/printer/print/text", json={
        "content": "Hello, ACO!",
        "copies": 1,
    }, headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_print_qr(client):
    r = client.post("/printer/print/qr", json={
        "content": "https://aco-recycling.com",
    }, headers=AUTH)
    assert r.status_code == 202


def test_print_image(client):
    r = client.post("/printer/print/image", json={
        "content": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    }, headers=AUTH)
    assert r.status_code == 202


def test_print_empty_content(client):
    r = client.post("/printer/print/text", json={"content": "   "}, headers=AUTH)
    assert r.status_code == 422


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_print_idempotency(client):
    payload = {"content": "Idempotent job", "idempotency_key": "test-key-001"}
    r1 = client.post("/printer/print/text", json=payload, headers=AUTH)
    r2 = client.post("/printer/print/text", json=payload, headers=AUTH)
    assert r1.status_code == 202
    assert r2.status_code == 409


# ── Reprint ───────────────────────────────────────────────────────────────────

def test_reprint_existing_job(client):
    r = client.post("/printer/print/text", json={"content": "Reprint me"}, headers=AUTH)
    job_id = r.json()["job_id"]
    rr = client.post("/printer/reprint", json={"job_id": job_id}, headers=AUTH)
    assert rr.status_code == 202
    assert rr.json()["original_job_id"] == job_id


def test_reprint_nonexistent_job(client):
    r = client.post("/printer/reprint", json={"job_id": "00000000-0000-0000-0000-000000000000"}, headers=AUTH)
    assert r.status_code == 404


# ── Loglar ────────────────────────────────────────────────────────────────────

def test_logs_list(client):
    r = client.get("/logs", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "jobs" in body
    assert "total" in body


def test_logs_export_csv(client):
    r = client.get("/logs/export", headers=AUTH)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "id" in r.text


def test_logs_prediction(client):
    r = client.get("/logs/prediction", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "paper_remaining_cm" in body
    assert "estimated_prints_left" in body


# ── Chaos testi ───────────────────────────────────────────────────────────────

def test_chaos_paper_out(client):
    r = client.post("/printer/print/text", json={
        "content": "FAIL_PAPER trigger",
        "idempotency_key": "chaos-paper-001",
    }, headers=AUTH)
    assert r.status_code == 202


def test_chaos_overheat(client):
    # Simülatörü sıfırla, sonra FAIL_HEAT gönder
    r = client.post("/printer/print/text", json={
        "content": "FAIL_HEAT trigger",
        "idempotency_key": "chaos-heat-001",
    }, headers=AUTH)
    assert r.status_code == 202