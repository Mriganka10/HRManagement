"""Database schema (all tables). ``db.init_db`` runs these on every start; they are idempotent.

Rules for changing the schema (see docs/ARCHITECTURE.md):
- never edit or drop an existing column in place; add new columns with ``db.ensure_column``
  in ``ADDITIVE_COLUMNS`` so databases that already exist keep booting;
- every table has ``created_at`` (ISO-8601 UTC text) and an integer/bigserial ``id``.
"""
from __future__ import annotations


def statements(postgres: bool) -> list[str]:
    pk = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real = "DOUBLE PRECISION" if postgres else "REAL"
    big = "BIGINT"
    return [
        # ------------------------------------------------------------------ candidates & sign-in
        """CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            full_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS otp_codes (
            id {pk}, email TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        )""",
        # ------------------------------------------------------------------ recruitment
        f"""CREATE TABLE IF NOT EXISTS job_openings (
            id {pk},
            key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            employment_type TEXT NOT NULL DEFAULT 'Full-time',
            experience TEXT NOT NULL DEFAULT '',
            min_years {real} NOT NULL DEFAULT 0,
            skills TEXT NOT NULL DEFAULT '[]',
            description TEXT NOT NULL DEFAULT '',
            openings INTEGER NOT NULL DEFAULT 1,
            annual_ctc {real} NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS applications (
            id {pk}, email TEXT NOT NULL, role_key TEXT NOT NULL, role_title TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            experience_years {real} NOT NULL DEFAULT 0, resume_name TEXT NOT NULL DEFAULT '',
            resume_path TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL,
            ats_score {real}, ats_report TEXT, test_percent {real}, interview_score {real},
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (email, role_key)
        )""",
        f"""CREATE TABLE IF NOT EXISTS mock_tests (
            id {pk},
            application_id {big} NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            email TEXT NOT NULL, questions TEXT NOT NULL, topics TEXT NOT NULL DEFAULT '[]',
            time_limit_seconds INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT NOT NULL, completed_at TEXT, answers TEXT, scorecard TEXT,
            percent {real}, integrity TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS interviews (
            id {pk},
            application_id {big} NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            email TEXT NOT NULL, questions TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '{{}}',
            status TEXT NOT NULL DEFAULT 'in_progress', started_at TEXT NOT NULL, completed_at TEXT,
            report TEXT, score {real}, integrity TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS email_log (
            id {pk}, application_id {big}, recipient TEXT NOT NULL, kind TEXT NOT NULL,
            subject TEXT NOT NULL, backend TEXT NOT NULL, status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS pipeline_events (
            id {pk}, application_id {big} NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL,
            from_stage TEXT NOT NULL DEFAULT '', to_stage TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '{{}}', created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS onboarding (
            id {pk},
            application_id {big} NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            prefill TEXT NOT NULL DEFAULT '{{}}',
            form TEXT NOT NULL DEFAULT '{{}}',
            employee_id {big},
            submitted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        # ------------------------------------------------------------------ people
        f"""CREATE TABLE IF NOT EXISTS accounts (
            id {pk},
            user_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            session_version INTEGER NOT NULL DEFAULT 1,
            employee_id {big},
            failed_logins INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            last_login_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS employees (
            id {pk},
            employee_code TEXT NOT NULL UNIQUE,
            account_id {big},
            application_id {big},
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL DEFAULT '',
            designation TEXT NOT NULL DEFAULT '',
            department TEXT NOT NULL DEFAULT '',
            role_key TEXT NOT NULL DEFAULT '',
            manager_id {big},
            date_of_joining TEXT NOT NULL,
            employment_type TEXT NOT NULL DEFAULT 'Full-time',
            work_location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'probation',
            probation_end TEXT,
            exit_date TEXT,
            date_of_birth TEXT NOT NULL DEFAULT '',
            gender TEXT NOT NULL DEFAULT '',
            blood_group TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            emergency_contact_name TEXT NOT NULL DEFAULT '',
            emergency_contact_phone TEXT NOT NULL DEFAULT '',
            pan_number TEXT NOT NULL DEFAULT '',
            bank_account_name TEXT NOT NULL DEFAULT '',
            bank_account_number TEXT NOT NULL DEFAULT '',
            bank_ifsc TEXT NOT NULL DEFAULT '',
            linkedin TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '[]',
            education TEXT NOT NULL DEFAULT '[]',
            experience TEXT NOT NULL DEFAULT '[]',
            certifications TEXT NOT NULL DEFAULT '[]',
            annual_ctc {real} NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS documents (
            id {pk}, employee_id {big} NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
            storage_key TEXT NOT NULL, content_type TEXT NOT NULL DEFAULT 'text/html', created_at TEXT NOT NULL
        )""",
        # ------------------------------------------------------------------ time off & attendance
        f"""CREATE TABLE IF NOT EXISTS leave_types (
            id {pk}, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, annual_quota {real} NOT NULL,
            paid INTEGER NOT NULL DEFAULT 1, carry_forward INTEGER NOT NULL DEFAULT 0,
            min_notice_days INTEGER NOT NULL DEFAULT 0, max_consecutive_days INTEGER NOT NULL DEFAULT 0,
            allow_half_day INTEGER NOT NULL DEFAULT 1, allowed_in_probation INTEGER NOT NULL DEFAULT 1,
            description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
        )""",
        f"""CREATE TABLE IF NOT EXISTS leave_requests (
            id {pk}, employee_id {big} NOT NULL, leave_type_id {big} NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, days {real} NOT NULL,
            half_day INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending', approver_employee_id {big},
            decided_by TEXT NOT NULL DEFAULT '', decided_at TEXT, decision_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""",
        f"CREATE TABLE IF NOT EXISTS holidays (id {pk}, holiday_date TEXT NOT NULL UNIQUE, name TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS attendance (
            id {pk}, employee_id {big} NOT NULL, work_date TEXT NOT NULL,
            check_in TEXT, check_out TEXT, status TEXT NOT NULL DEFAULT 'present',
            source TEXT NOT NULL DEFAULT 'web', note TEXT NOT NULL DEFAULT '',
            UNIQUE (employee_id, work_date)
        )""",
        # ------------------------------------------------------------------ payroll
        f"""CREATE TABLE IF NOT EXISTS salary_structures (
            id {pk}, employee_id {big} NOT NULL, annual_ctc {real} NOT NULL,
            components TEXT NOT NULL, monthly_tds {real} NOT NULL DEFAULT 0,
            effective_from TEXT NOT NULL, created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS payslips (
            id {pk}, employee_id {big} NOT NULL, period TEXT NOT NULL,
            working_days {real} NOT NULL, paid_days {real} NOT NULL, lop_days {real} NOT NULL,
            earnings TEXT NOT NULL, deductions TEXT NOT NULL,
            gross {real} NOT NULL, total_deductions {real} NOT NULL, net_pay {real} NOT NULL,
            generated_at TEXT NOT NULL, UNIQUE (employee_id, period)
        )""",
        # ------------------------------------------------------------------ service desk & content
        f"""CREATE TABLE IF NOT EXISTS service_requests (
            id {pk}, ref TEXT NOT NULL UNIQUE, employee_id {big} NOT NULL, kind TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            amount {real}, payload TEXT NOT NULL DEFAULT '{{}}', attachment_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', resolution TEXT NOT NULL DEFAULT '',
            handled_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS request_comments (
            id {pk}, request_id {big} NOT NULL, author TEXT NOT NULL, author_role TEXT NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS policies (
            id {pk}, slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'General',
            body TEXT NOT NULL, updated_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS performance_reviews (
            id {pk}, employee_id {big} NOT NULL, period TEXT NOT NULL, rating {real} NOT NULL,
            competencies TEXT NOT NULL DEFAULT '{{}}', notes TEXT NOT NULL DEFAULT '',
            reviewer TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (employee_id, period)
        )""",
        f"""CREATE TABLE IF NOT EXISTS notifications (
            id {pk}, account_id {big} NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '', is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS audit_log (
            id {pk}, actor TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL,
            entity_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '{{}}', created_at TEXT NOT NULL
        )""",
        f"CREATE TABLE IF NOT EXISTS rate_events (id {pk}, bucket TEXT NOT NULL, ts {real} NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS llm_usage (
            id {pk}, feature TEXT NOT NULL, user_email TEXT NOT NULL DEFAULT '', input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cost_usd {real} NOT NULL, ok INTEGER NOT NULL, day TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        # ------------------------------------------------------------------ indexes
        "CREATE INDEX IF NOT EXISTS idx_applications_email ON applications (email)",
        "CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications (stage)",
        "CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes (email)",
        "CREATE INDEX IF NOT EXISTS idx_events_app ON pipeline_events (application_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_app ON email_log (application_id)",
        "CREATE INDEX IF NOT EXISTS idx_rate_bucket ON rate_events (bucket, ts)",
        "CREATE INDEX IF NOT EXISTS idx_employees_manager ON employees (manager_id)",
        "CREATE INDEX IF NOT EXISTS idx_leave_employee ON leave_requests (employee_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_leave_approver ON leave_requests (approver_employee_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance (work_date)",
        "CREATE INDEX IF NOT EXISTS idx_requests_employee ON service_requests (employee_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_requests_status ON service_requests (status)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_account ON notifications (account_id, is_read)",
        "CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log (entity, entity_id)",
    ]


# (table, column, definition) — columns added after a table first shipped.
ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "lang", "TEXT"),      # candidate's interface/email language (en, ar)
    ("accounts", "lang", "TEXT"),   # employee/HR interface/email language (en, ar)
]
