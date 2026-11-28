"""Application settings, read once from environment variables (and a local .env file).

Every setting is prefixed ``HRM_`` so it can live next to other services' settings in
AWS Secrets Manager / the ECS task definition without collisions. See docs/CONFIGURATION.md.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


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


@dataclass(frozen=True)
class Settings:
    # --- app
    environment: str = "development"      # development | production
    company_name: str = "Kairoz"
    secret_key: str = "dev-only-change-me"
    public_base_url: str = "http://127.0.0.1:8000"
    timezone: str = "Asia/Kolkata"
    default_language: str = "en"
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""

    # --- sessions & sign-in
    cookie_secure: bool = False
    session_max_age_seconds: int = 12 * 3600
    dev_return_otp: bool = True
    otp_ttl_minutes: int = 10
    password_min_length: int = 10
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    bootstrap_hr_email: str = ""
    bootstrap_hr_name: str = "HR Administrator"
    bootstrap_hr_password: str = ""

    # --- recruitment
    ats_pass_score: float = 75
    test_pass_percent: float = 70
    interview_pass_score: float = 75
    auto_select: bool = True              # interview pass -> selection + onboarding email without HR click
    test_length: str = "standard"
    test_difficulty: str = "mixed"
    test_grace_seconds: int = 60
    interview_mode: str = "standard"
    max_upload_mb: int = 5

    # --- people operations
    probation_months: int = 6
    work_week_days: int = 5               # 5 = Mon-Fri, 6 = Mon-Sat
    office_start_time: str = "09:30"      # check-ins after this (+ grace) are marked late
    late_grace_minutes: int = 15

    # --- storage: "local" (data/files) or "s3"
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = "hrm"
    aws_region: str = "ap-south-1"

    # --- email: "console" | "smtp" | "ses"
    email_backend: str = "console"
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))


def _database_url() -> str:
    """HRM_DATABASE_URL, or one built from parts (how ECS injects the RDS secret: host/user/password)."""
    url = _str("HRM_DATABASE_URL")
    host = _str("HRM_DB_HOST")
    if url or not host:
        return url
    from urllib.parse import quote

    user, password = quote(_str("HRM_DB_USER", "hrm"), safe=""), quote(_str("HRM_DB_PASSWORD"), safe="")
    return f"postgresql://{user}:{password}@{host}:{_str('HRM_DB_PORT', '5432')}/{_str('HRM_DB_NAME', 'hr_management')}?sslmode={_str('HRM_DB_SSLMODE', 'require')}"


def load_settings() -> Settings:
    load_dotenv()
    data_dir = Path(_str("HRM_DATA_DIR") or PROJECT_ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    smtp_host = _str("HRM_SMTP_HOST")
    environment = _str("HRM_ENVIRONMENT", "development").lower()
    production = environment == "production"
    return Settings(
        environment=environment,
        company_name=_str("HRM_COMPANY_NAME", "Kairoz"),
        secret_key=_str("HRM_SECRET_KEY", "dev-only-change-me"),
        public_base_url=_str("HRM_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        timezone=_str("HRM_TIMEZONE", "Asia/Kolkata"),
        default_language=_str("HRM_DEFAULT_LANGUAGE", "en"),
        data_dir=data_dir,
        database_url=_database_url(),
        cookie_secure=_bool("HRM_COOKIE_SECURE", production),
        session_max_age_seconds=_int("HRM_SESSION_MAX_AGE_SECONDS", 12 * 3600),
        # Never show OTPs on screen in production, whatever the env says.
        dev_return_otp=_bool("HRM_DEV_RETURN_OTP", not production) and not production,
        otp_ttl_minutes=_int("HRM_OTP_TTL_MINUTES", 10),
        password_min_length=max(8, _int("HRM_PASSWORD_MIN_LENGTH", 10)),
        login_max_failures=_int("HRM_LOGIN_MAX_FAILURES", 5),
        login_lock_minutes=_int("HRM_LOGIN_LOCK_MINUTES", 15),
        bootstrap_hr_email=_str("HRM_BOOTSTRAP_HR_EMAIL").lower(),
        bootstrap_hr_name=_str("HRM_BOOTSTRAP_HR_NAME", "HR Administrator"),
        bootstrap_hr_password=_str("HRM_BOOTSTRAP_HR_PASSWORD"),
        ats_pass_score=_float("HRM_ATS_PASS_SCORE", 75),
        test_pass_percent=_float("HRM_TEST_PASS_PERCENT", 70),
        interview_pass_score=_float("HRM_INTERVIEW_PASS_SCORE", 75),
        auto_select=_bool("HRM_AUTO_SELECT", True),
        test_length=_str("HRM_TEST_LENGTH", "standard").lower(),
        test_difficulty=_str("HRM_TEST_DIFFICULTY", "mixed").lower(),
        test_grace_seconds=_int("HRM_TEST_GRACE_SECONDS", 60),
        interview_mode=_str("HRM_INTERVIEW_MODE", "standard").lower(),
        max_upload_mb=_int("HRM_MAX_UPLOAD_MB", _int("HRM_MAX_RESUME_MB", 5)),
        probation_months=_int("HRM_PROBATION_MONTHS", 6),
        work_week_days=6 if _int("HRM_WORK_WEEK_DAYS", 5) == 6 else 5,
        office_start_time=_str("HRM_OFFICE_START_TIME", "09:30"),
        late_grace_minutes=_int("HRM_LATE_GRACE_MINUTES", 15),
        storage_backend=_str("HRM_STORAGE_BACKEND", "local").lower(),
        s3_bucket=_str("HRM_S3_BUCKET"),
        s3_prefix=_str("HRM_S3_PREFIX", "hrm").strip("/"),
        aws_region=_str("HRM_AWS_REGION", _str("AWS_REGION", "ap-south-1")),
        email_backend=_str("HRM_EMAIL_BACKEND", "smtp" if smtp_host else "console").lower(),
        email_from=_str("HRM_EMAIL_FROM", _str("HRM_SMTP_FROM")),
        smtp_host=smtp_host,
        smtp_port=_int("HRM_SMTP_PORT", 587),
        smtp_username=_str("HRM_SMTP_USERNAME"),
        smtp_password=_str("HRM_SMTP_PASSWORD"),
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


# Fixed offsets used only when the IANA time-zone database is unavailable
# (Windows without the ``tzdata`` package). India has no daylight saving, so this is exact.
_FALLBACK_OFFSETS = {"Asia/Kolkata": (5, 30), "Asia/Calcutta": (5, 30), "UTC": (0, 0), "Etc/UTC": (0, 0)}


def company_tz(name: str | None = None) -> tzinfo:
    """The company time zone (HRM_TIMEZONE) as a tzinfo.

    Uses ``zoneinfo``; if the time-zone database is missing (common on Windows when
    ``tzdata`` is not installed) it falls back to a fixed offset instead of crashing.
    """
    key = name or get_settings().timezone
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        hours, minutes = _FALLBACK_OFFSETS.get(key, (0, 0))
        if key not in _FALLBACK_OFFSETS:
            logging.getLogger(__name__).warning(
                "Time zone %r not found and no fallback known; using UTC. Run: python -m pip install tzdata", key)
        return timezone(timedelta(hours=hours, minutes=minutes), key)
