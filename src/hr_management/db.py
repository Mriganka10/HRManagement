"""Database access: SQLite locally, PostgreSQL in production (same SQL for both).

Design notes (same approach as the Job-Hunting-Agent project):
- Plain SQL, no ORM. ``?`` placeholders are translated to ``%s`` for PostgreSQL.
- Tables are created with ``CREATE TABLE IF NOT EXISTS``; later schema changes are
  added with ``_ensure_column`` so existing databases keep booting.
- JSON payloads are stored as TEXT and decoded on read.
- Stage changes use compare-and-set (``WHERE stage = ?``) so two browser tabs can
  never start or submit the same assessment twice.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .settings import get_settings

_init_lock = threading.Lock()

JSON_COLUMNS = {"ats_report", "questions", "topics", "answers", "scorecard", "integrity", "report", "detail"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- connection

def _is_postgres() -> bool:
    return get_settings().is_postgres


def _sqlite_path() -> str:
    cfg = get_settings()
    if cfg.database_url.startswith("sqlite:///"):
        return cfg.database_url.replace("sqlite:///", "", 1)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg.data_dir / "hr_management.db")


@contextmanager
def connection() -> Iterator[Any]:
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
            yield conn
            conn.commit()
        return
    conn = sqlite3.connect(_sqlite_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sql(sql: str) -> str:
    return sql.replace("?", "%s") if _is_postgres() else sql


def _execute(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(_sql(sql), params)


def _decode(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for key in JSON_COLUMNS & item.keys():
        value = item[key]
        if isinstance(value, str) and value[:1] in "{[":
            try:
                item[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return item


def _one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    return _decode(_execute(conn, sql, params).fetchone())


def _all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [_decode(row) for row in _execute(conn, sql, params).fetchall()]  # type: ignore[misc]


def _insert(conn: Any, sql: str, params: tuple[Any, ...]) -> int:
    row = _execute(conn, sql.rstrip().rstrip(";") + " RETURNING id", params).fetchone()
    return int(dict(row)["id"])


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _ensure_column(conn: Any, table: str, column: str, definition: str) -> None:
    if _is_postgres():
        _execute(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        return
    columns = {row["name"] for row in _all(conn, f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# --------------------------------------------------------------------------- schema

def init_db() -> None:
    pk = "BIGSERIAL PRIMARY KEY" if _is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real = "DOUBLE PRECISION" if _is_postgres() else "REAL"
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            full_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS otp_codes (
            id {pk},
            email TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS applications (
            id {pk},
            email TEXT NOT NULL,
            role_key TEXT NOT NULL,
            role_title TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            experience_years {real} NOT NULL DEFAULT 0,
            resume_name TEXT NOT NULL DEFAULT '',
            resume_path TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL,
            ats_score {real},
            ats_report TEXT,
            test_percent {real},
            interview_score {real},
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (email, role_key)
        )""",
        f"""CREATE TABLE IF NOT EXISTS mock_tests (
            id {pk},
            application_id BIGINT NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            questions TEXT NOT NULL,
            topics TEXT NOT NULL DEFAULT '[]',
            time_limit_seconds INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            answers TEXT,
            scorecard TEXT,
            percent {real},
            integrity TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS interviews (
            id {pk},
            application_id BIGINT NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            questions TEXT NOT NULL,
            answers TEXT NOT NULL DEFAULT '{{}}',
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            report TEXT,
            score {real},
            integrity TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS email_log (
            id {pk},
            application_id BIGINT,
            recipient TEXT NOT NULL,
            kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            backend TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS pipeline_events (
            id {pk},
            application_id BIGINT NOT NULL,
            actor TEXT NOT NULL,
            event TEXT NOT NULL,
            from_stage TEXT NOT NULL DEFAULT '',
            to_stage TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL
        )""",
        f"CREATE TABLE IF NOT EXISTS rate_events (id {pk}, bucket TEXT NOT NULL, ts {real} NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS llm_usage (
            id {pk},
            feature TEXT NOT NULL,
            user_email TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd {real} NOT NULL,
            ok INTEGER NOT NULL,
            day TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_applications_email ON applications (email)",
        "CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications (stage)",
        "CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes (email)",
        "CREATE INDEX IF NOT EXISTS idx_events_app ON pipeline_events (application_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_app ON email_log (application_id)",
        "CREATE INDEX IF NOT EXISTS idx_rate_bucket ON rate_events (bucket, ts)",
    ]
    with _init_lock, connection() as conn:
        if not _is_postgres():
            conn.execute("PRAGMA journal_mode = WAL")
        for statement in statements:
            _execute(conn, statement)


# --------------------------------------------------------------------------- users & OTP

def ensure_user(email: str) -> None:
    email = normalize_email(email)
    with connection() as conn:
        if not _one(conn, "SELECT email FROM users WHERE email = ?", (email,)):
            _execute(conn, "INSERT INTO users (email, created_at) VALUES (?, ?)", (email, now_iso()))


def touch_login(email: str) -> None:
    with connection() as conn:
        _execute(conn, "UPDATE users SET last_login_at = ? WHERE email = ?", (now_iso(), normalize_email(email)))


def save_otp(email: str, code_hash: str, expires_at: datetime) -> None:
    email = normalize_email(email)
    with connection() as conn:
        # Only the newest code is valid.
        _execute(conn, "UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0", (email,))
        _execute(
            conn,
            "INSERT INTO otp_codes (email, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (email, code_hash, expires_at.isoformat(), now_iso()),
        )


def consume_otp(email: str, code_hash: str, *, compare, max_attempts: int = 5) -> str:
    """Return "ok", "invalid", "expired" or "locked". Wrong guesses are counted per code."""
    email = normalize_email(email)
    with connection() as conn:
        row = _one(conn, "SELECT * FROM otp_codes WHERE email = ? AND used = 0 ORDER BY id DESC LIMIT 1", (email,))
        if not row:
            return "invalid"
        if int(row["attempts"]) >= max_attempts:
            return "locked"
        if (parse_time(row["expires_at"]) or utcnow()) < utcnow():
            return "expired"
        if not compare(row["code_hash"], code_hash):
            _execute(conn, "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            return "invalid"
        _execute(conn, "UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        return "ok"


# --------------------------------------------------------------------------- applications

def create_application(
    *, email: str, role_key: str, role_title: str, full_name: str, phone: str,
    experience_years: float, resume_name: str, resume_path: str, stage: str,
) -> int:
    stamp = now_iso()
    with connection() as conn:
        return _insert(
            conn,
            """INSERT INTO applications (email, role_key, role_title, full_name, phone, experience_years,
                   resume_name, resume_path, stage, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (normalize_email(email), role_key, role_title, full_name, phone, float(experience_years),
             resume_name, resume_path, stage, stamp, stamp),
        )


def application_for_role(email: str, role_key: str) -> dict[str, Any] | None:
    with connection() as conn:
        return _one(conn, "SELECT * FROM applications WHERE email = ? AND role_key = ?", (normalize_email(email), role_key))


def application(application_id: int, email: str | None = None) -> dict[str, Any] | None:
    """Fetch one application; pass ``email`` to enforce ownership."""
    with connection() as conn:
        if email is None:
            return _one(conn, "SELECT * FROM applications WHERE id = ?", (application_id,))
        return _one(conn, "SELECT * FROM applications WHERE id = ? AND email = ?", (application_id, normalize_email(email)))


def applications_for_user(email: str) -> list[dict[str, Any]]:
    with connection() as conn:
        return _all(conn, "SELECT * FROM applications WHERE email = ? ORDER BY id DESC", (normalize_email(email),))


def all_applications(stage: str = "", limit: int = 500) -> list[dict[str, Any]]:
    with connection() as conn:
        if stage:
            return _all(conn, "SELECT * FROM applications WHERE stage = ? ORDER BY updated_at DESC LIMIT ?", (stage, limit))
        return _all(conn, "SELECT * FROM applications ORDER BY updated_at DESC LIMIT ?", (limit,))


def update_application(application_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    columns = ", ".join(f"{name} = ?" for name in fields)
    values = tuple(_dump(value) if isinstance(value, (dict, list)) else value for value in fields.values())
    with connection() as conn:
        _execute(conn, f"UPDATE applications SET {columns} WHERE id = ?", (*values, application_id))


def transition_stage(application_id: int, from_stages: tuple[str, ...], to_stage: str, **fields: Any) -> bool:
    """Atomically move an application between stages. False if it was not in ``from_stages``."""
    fields["stage"] = to_stage
    fields["updated_at"] = now_iso()
    columns = ", ".join(f"{name} = ?" for name in fields)
    values = tuple(_dump(value) if isinstance(value, (dict, list)) else value for value in fields.values())
    marks = ", ".join("?" for _ in from_stages)
    with connection() as conn:
        cursor = _execute(
            conn,
            f"UPDATE applications SET {columns} WHERE id = ? AND stage IN ({marks})",
            (*values, application_id, *from_stages),
        )
        return cursor.rowcount == 1


def stage_counts() -> dict[str, int]:
    with connection() as conn:
        return {row["stage"]: int(row["total"]) for row in _all(conn, "SELECT stage, COUNT(*) AS total FROM applications GROUP BY stage")}


# --------------------------------------------------------------------------- mock tests

def create_mock_test(*, application_id: int, email: str, questions: list, topics: list, time_limit_seconds: int) -> int:
    with connection() as conn:
        return _insert(
            conn,
            """INSERT INTO mock_tests (application_id, email, questions, topics, time_limit_seconds, started_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (application_id, normalize_email(email), _dump(questions), _dump(topics), int(time_limit_seconds), now_iso()),
        )


def mock_test_for_application(application_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        return _one(conn, "SELECT * FROM mock_tests WHERE application_id = ?", (application_id,))


def save_test_answers(test_id: int, answers: dict, integrity: dict) -> bool:
    """Autosave while the test is running, so a refresh or closed tab loses nothing."""
    with connection() as conn:
        cursor = _execute(
            conn, "UPDATE mock_tests SET answers = ?, integrity = ? WHERE id = ? AND status = 'in_progress'",
            (_dump(answers), _dump(integrity), test_id),
        )
        return cursor.rowcount == 1


def complete_mock_test(test_id: int, *, answers: dict, scorecard: dict, percent: float, integrity: dict) -> bool:
    with connection() as conn:
        cursor = _execute(
            conn,
            """UPDATE mock_tests SET status = 'completed', completed_at = ?, answers = ?, scorecard = ?, percent = ?, integrity = ?
               WHERE id = ? AND status = 'in_progress'""",
            (now_iso(), _dump(answers), _dump(scorecard), float(percent), _dump(integrity), test_id),
        )
        return cursor.rowcount == 1


# --------------------------------------------------------------------------- interviews

def create_interview(*, application_id: int, email: str, questions: list) -> int:
    with connection() as conn:
        return _insert(
            conn,
            "INSERT INTO interviews (application_id, email, questions, started_at) VALUES (?, ?, ?, ?)",
            (application_id, normalize_email(email), _dump(questions), now_iso()),
        )


def interview_for_application(application_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        return _one(conn, "SELECT * FROM interviews WHERE application_id = ?", (application_id,))


def save_interview_answers(interview_id: int, answers: dict, integrity: dict) -> bool:
    with connection() as conn:
        cursor = _execute(
            conn, "UPDATE interviews SET answers = ?, integrity = ? WHERE id = ? AND status = 'in_progress'",
            (_dump(answers), _dump(integrity), interview_id),
        )
        return cursor.rowcount == 1


def complete_interview(interview_id: int, *, answers: dict, report: dict, score: float, integrity: dict) -> bool:
    with connection() as conn:
        cursor = _execute(
            conn,
            """UPDATE interviews SET status = 'completed', completed_at = ?, answers = ?, report = ?, score = ?, integrity = ?
               WHERE id = ? AND status = 'in_progress'""",
            (now_iso(), _dump(answers), _dump(report), float(score), _dump(integrity), interview_id),
        )
        return cursor.rowcount == 1


# --------------------------------------------------------------------------- audit & email log

def add_event(application_id: int, event: str, *, actor: str, from_stage: str = "", to_stage: str = "", detail: dict | None = None) -> None:
    with connection() as conn:
        _execute(
            conn,
            """INSERT INTO pipeline_events (application_id, actor, event, from_stage, to_stage, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (application_id, actor, event, from_stage, to_stage, _dump(detail or {}), now_iso()),
        )


def events_for_application(application_id: int) -> list[dict[str, Any]]:
    with connection() as conn:
        return _all(conn, "SELECT * FROM pipeline_events WHERE application_id = ? ORDER BY id", (application_id,))


def log_email(*, application_id: int | None, recipient: str, kind: str, subject: str, backend: str, status: str, error: str = "") -> None:
    with connection() as conn:
        _execute(
            conn,
            """INSERT INTO email_log (application_id, recipient, kind, subject, backend, status, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (application_id, normalize_email(recipient), kind, subject, backend, status, error[:500], now_iso()),
        )


def emails(application_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with connection() as conn:
        if application_id is None:
            return _all(conn, "SELECT * FROM email_log ORDER BY id DESC LIMIT ?", (limit,))
        return _all(conn, "SELECT * FROM email_log WHERE application_id = ? ORDER BY id DESC", (application_id,))


# --------------------------------------------------------------------------- rate limits & LLM spend (used by engines)

def rate_hit(bucket: str, limit: int, window_seconds: int, *, now: float | None = None) -> tuple[bool, int]:
    """Sliding-window limiter. Returns (allowed, retry_after_seconds)."""
    current = now if now is not None else time.time()
    start = current - window_seconds
    with connection() as conn:
        _execute(conn, "DELETE FROM rate_events WHERE bucket = ? AND ts < ?", (bucket, start))
        rows = _all(conn, "SELECT ts FROM rate_events WHERE bucket = ? ORDER BY ts", (bucket,))
        if len(rows) >= limit:
            return False, max(1, int(float(rows[0]["ts"]) + window_seconds - current))
        _execute(conn, "INSERT INTO rate_events (bucket, ts) VALUES (?, ?)", (bucket, current))
        return True, 0


def record_llm_usage(feature: str, *, user_email: str, input_tokens: int, output_tokens: int, cost_usd: float, ok: bool) -> None:
    with connection() as conn:
        _execute(
            conn,
            """INSERT INTO llm_usage (feature, user_email, input_tokens, output_tokens, cost_usd, ok, day, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (feature, normalize_email(user_email), int(input_tokens), int(output_tokens), float(cost_usd), int(bool(ok)),
             utcnow().date().isoformat(), now_iso()),
        )


def llm_spend(*, user_email: str = "") -> float:
    day = utcnow().date().isoformat()
    with connection() as conn:
        if user_email:
            row = _one(conn, "SELECT COALESCE(SUM(cost_usd), 0) AS spent FROM llm_usage WHERE day = ? AND user_email = ?",
                       (day, normalize_email(user_email)))
        else:
            row = _one(conn, "SELECT COALESCE(SUM(cost_usd), 0) AS spent FROM llm_usage WHERE day = ?", (day,))
        return float((row or {}).get("spent") or 0)
