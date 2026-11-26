"""Application settings, read once from environment variables (and a local .env file).

Every setting is prefixed ``HRM_`` so it can live next to other services' settings in
the same AWS Secrets Manager / ECS task definition later without collisions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines; real environment variables always win."""
    candidates = [path] if path else [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    env_file = next((item for item in candidates if item and item.is_file()), None)
    if env_file is None:
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in os.getenv(name, "").split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    company_name: str = "Kairoz"
    secret_key: str = "dev-only-change-me"
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""
    cookie_secure: bool = False
    dev_return_otp: bool = True
    otp_ttl_minutes: int = 10
    session_max_age_seconds: int = 7 * 24 * 3600
    hr_emails: tuple[str, ...] = field(default_factory=tuple)
    public_base_url: str = "http://127.0.0.1:8000"

    # Hiring thresholds (a score equal to the threshold passes).
    ats_pass_score: float = 75
    test_pass_percent: float = 70
    interview_pass_score: float = 75

    # Assessment shape
    test_length: str = "standard"          # quick=10, standard=20, full=30 questions
    test_difficulty: str = "mixed"
    test_grace_seconds: int = 60           # late submissions within the grace period still count
    interview_mode: str = "standard"       # quick=5, standard=8, deep=10 questions
    max_resume_mb: int = 5

    # Email: "console" prints to the terminal and saves to data/outbox; "smtp" sends for real.
    email_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))


def load_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.getenv("HRM_DATA_DIR", "") or PROJECT_ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    smtp_host = os.getenv("HRM_SMTP_HOST", "").strip()
    return Settings(
        company_name=os.getenv("HRM_COMPANY_NAME", "Kairoz").strip() or "Kairoz",
        secret_key=os.getenv("HRM_SECRET_KEY", "").strip() or "dev-only-change-me",
        data_dir=data_dir,
        database_url=os.getenv("HRM_DATABASE_URL", "").strip(),
        cookie_secure=_bool("HRM_COOKIE_SECURE", False),
        dev_return_otp=_bool("HRM_DEV_RETURN_OTP", True),
        otp_ttl_minutes=_int("HRM_OTP_TTL_MINUTES", 10),
        session_max_age_seconds=_int("HRM_SESSION_MAX_AGE_SECONDS", 7 * 24 * 3600),
        hr_emails=_csv("HRM_HR_EMAILS"),
        public_base_url=os.getenv("HRM_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        ats_pass_score=_float("HRM_ATS_PASS_SCORE", 75),
        test_pass_percent=_float("HRM_TEST_PASS_PERCENT", 70),
        interview_pass_score=_float("HRM_INTERVIEW_PASS_SCORE", 75),
        test_length=os.getenv("HRM_TEST_LENGTH", "standard").strip().lower() or "standard",
        test_difficulty=os.getenv("HRM_TEST_DIFFICULTY", "mixed").strip().lower() or "mixed",
        test_grace_seconds=_int("HRM_TEST_GRACE_SECONDS", 60),
        interview_mode=os.getenv("HRM_INTERVIEW_MODE", "standard").strip().lower() or "standard",
        max_resume_mb=_int("HRM_MAX_RESUME_MB", 5),
        email_backend=(os.getenv("HRM_EMAIL_BACKEND", "").strip().lower() or ("smtp" if smtp_host else "console")),
        smtp_host=smtp_host,
        smtp_port=_int("HRM_SMTP_PORT", 587),
        smtp_username=os.getenv("HRM_SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("HRM_SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("HRM_SMTP_FROM", "").strip(),
        smtp_use_tls=_bool("HRM_SMTP_USE_TLS", True),
    )


settings = load_settings()


def get_settings() -> Settings:
    """Always call this instead of importing ``settings`` directly, so reloads are seen."""
    return settings


def reload_settings() -> Settings:
    """Re-read the environment (used by tests that change HRM_* variables)."""
    global settings
    settings = load_settings()
    return settings
