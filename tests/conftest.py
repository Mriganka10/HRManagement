"""Every test gets a fresh data directory and database, with emails printed to an outbox."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SAMPLES = ROOT / "samples"

HR_EMAIL = "hr@example.com"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HRM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HRM_DATABASE_URL", "")
    monkeypatch.setenv("HRM_RATE_LIMITS", "off")
    monkeypatch.setenv("HRM_DEV_RETURN_OTP", "true")
    monkeypatch.setenv("HRM_EMAIL_BACKEND", "console")
    monkeypatch.setenv("HRM_HR_EMAILS", HR_EMAIL)
    monkeypatch.setenv("HRM_SECRET_KEY", "test-secret")
    for name in ("HRM_LLM_API_KEY", "HRM_INTERVIEW_LLM_API_KEY", "HRM_MOCK_TEST_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from hr_management import settings

    settings.reload_settings()
    yield
    settings.reload_settings()


@pytest.fixture
def make_client():
    from hr_management.web import create_app

    def _make(email: str) -> TestClient:
        client = TestClient(create_app())
        otp = client.post("/api/auth/request-otp", json={"email": email}).json()["dev_otp"]
        response = client.post("/api/auth/verify", json={"email": email, "otp": otp})
        assert response.status_code == 200, response.text
        return client

    return _make


def apply(client: TestClient, resume: str, role_key: str = "backend-developer", years: float = 4):
    path = SAMPLES / resume
    with path.open("rb") as handle:
        return client.post(
            "/api/applications",
            data={"role_key": role_key, "full_name": "Rahul Verma", "experience_years": str(years), "phone": ""},
            files={"resume": (path.name, handle, "text/plain")},
        )
