"""Every test gets a fresh data directory and database; emails are printed to an outbox."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SAMPLES = ROOT / "samples"

HR_PASSWORD = "HrAdmin2026x"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HRM_DATA_DIR", str(tmp_path / "data"))
    # Set HRM_TEST_DATABASE_URL=postgresql://... to run the suite against PostgreSQL (CI does).
    pg_url = os.getenv("HRM_TEST_DATABASE_URL", "")
    monkeypatch.setenv("HRM_DATABASE_URL", pg_url)
    if pg_url:
        import psycopg

        with psycopg.connect(pg_url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("HRM_ENVIRONMENT", "development")
    monkeypatch.setenv("HRM_RATE_LIMITS", "off")
    monkeypatch.setenv("HRM_DEV_RETURN_OTP", "true")
    monkeypatch.setenv("HRM_EMAIL_BACKEND", "console")
    monkeypatch.setenv("HRM_STORAGE_BACKEND", "local")
    monkeypatch.setenv("HRM_SECRET_KEY", "test-secret")
    monkeypatch.setenv("HRM_AUTO_SELECT", "true")
    monkeypatch.setenv("HRM_BOOTSTRAP_HR_EMAIL", "")
    for name in ("HRM_LLM_API_KEY", "HRM_INTERVIEW_LLM_API_KEY", "HRM_MOCK_TEST_LLM_API_KEY", "HRM_ASSISTANT_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from hr_management import settings

    settings.reload_settings()
    yield
    settings.reload_settings()


@pytest.fixture
def app():
    from hr_management.web import create_app

    return create_app()


@pytest.fixture
def candidate_client(app):
    def _make(email: str) -> TestClient:
        client = TestClient(app)
        otp = client.post("/api/auth/request-otp", json={"email": email}).json()["dev_otp"]
        assert client.post("/api/auth/verify", json={"email": email, "otp": otp}).status_code == 200
        return client
    return _make


@pytest.fixture
def hr_client(app):
    from hr_management import db
    from hr_management.services.accounts import create_account

    account, _ = create_account(email="hr@kairoz.test", full_name="Hema HR", role="hr_admin", password=HR_PASSWORD)
    db.update("accounts", account["id"], {"must_change_password": 0})
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": account["user_id"], "password": HR_PASSWORD}).status_code == 200
    return client


def staff_client(app, user_id: str, password: str, *, change_to: str | None = None) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200, response.text
    if change_to:
        r = client.post("/api/auth/change-password", json={"current_password": password, "new_password": change_to})
        assert r.status_code == 200, r.text
    return client


def apply(client: TestClient, resume: str, role_key: str = "backend-developer", years: float = 4):
    path = SAMPLES / resume
    with path.open("rb") as handle:
        return client.post(
            "/api/applications",
            data={"role_key": role_key, "full_name": "Rahul Verma", "experience_years": str(years), "phone": ""},
            files={"resume": (path.name, handle, "text/plain")},
        )
