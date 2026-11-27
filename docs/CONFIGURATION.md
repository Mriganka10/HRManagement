# Configuration

All settings are environment variables prefixed `HRM_`.
* **Locally** they come from `.env`, copied from `.env.example`.
* **On AWS** they come from the ECS task definition, with secrets taken from Secrets Manager (see [AWS_DEPLOYMENT.md](AWS_DEPLOYMENT.md)).
* A real environment variable always overrides `.env`.

`settings.py` reads them once at start. Code must call `get_settings()` rather than importing the `settings` object, so that tests can reload it.

## App

| Variable | Default | Purpose |
|---|---|---|
| `HRM_ENVIRONMENT` | `development` | `production` forces secure cookies, never shows sign-in codes, hides `/docs`, refuses to start without a secret key, and blocks `seed-demo` |
| `HRM_COMPANY_NAME` | `Kairoz` | Shown in pages and emails |
| `HRM_SECRET_KEY` | dev key | Signs session cookies and hashes sign-in codes. Changing it signs everyone out. **Secret** |
| `HRM_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Used in email links and the logo URL in emails |
| `HRM_TIMEZONE` | `Asia/Kolkata` | Attendance times, the late cutoff and "today" |

## First HR administrator

| Variable | Purpose |
|---|---|
| `HRM_BOOTSTRAP_HR_EMAIL` | If no HR admin exists, one is created at start with this email |
| `HRM_BOOTSTRAP_HR_NAME` | Display name for that account |
| `HRM_BOOTSTRAP_HR_PASSWORD` | Optional fixed temporary password. Locally, if empty, a temporary password is printed. In production, if empty, nothing is created and you use `create-hr` instead |

## Recruitment

| Variable | Default | Purpose |
|---|---|---|
| `HRM_ATS_PASS_SCORE` | `75` | Resume score needed for the mock test (a score equal to the mark passes) |
| `HRM_TEST_PASS_PERCENT` | `70` | Mock test percentage needed for the interview |
| `HRM_INTERVIEW_PASS_SCORE` | `75` | Interview score needed for selection |
| `HRM_AUTO_SELECT` | `true` | `true`: a passed interview means the candidate is selected and the onboarding email goes out at once. `false`: HR decides on the hiring board |
| `HRM_TEST_LENGTH` | `standard` | `quick` = 10, `standard` = 20, `full` = 30 questions |
| `HRM_TEST_DIFFICULTY` | `mixed` | `mixed`, `easy`, `medium` or `hard` |
| `HRM_TEST_GRACE_SECONDS` | `60` | Network grace period after the timer ends |
| `HRM_INTERVIEW_MODE` | `standard` | `quick` = 5, `standard` = 8, `deep` = 10 questions |
| `HRM_MAX_UPLOAD_MB` | `5` | Maximum size for resumes and receipts |

## People operations

| Variable | Default | Purpose |
|---|---|---|
| `HRM_PROBATION_MONTHS` | `6` | Sets `probation_end` for new employees |
| `HRM_WORK_WEEK_DAYS` | `5` | `5` = Monday to Friday, `6` = Monday to Saturday (leave days, payroll working days, attendance) |
| `HRM_OFFICE_START_TIME` | `09:30` | Late cutoff = this time plus the grace minutes |
| `HRM_LATE_GRACE_MINUTES` | `15` | |

## Sign-in and sessions

| Variable | Default | Purpose |
|---|---|---|
| `HRM_DEV_RETURN_OTP` | `true` | Shows the candidate's code on screen. Always off in production |
| `HRM_OTP_TTL_MINUTES` | `10` | How long a candidate code is valid |
| `HRM_SESSION_MAX_AGE_SECONDS` | `43200` | Session length (12 hours) |
| `HRM_PASSWORD_MIN_LENGTH` | `10` | Minimum is 8 regardless |
| `HRM_LOGIN_MAX_FAILURES` / `HRM_LOGIN_LOCK_MINUTES` | `5` / `15` | Account lockout |
| `HRM_COOKIE_SECURE` | off in dev, on in production | HTTPS-only cookie |

## Database

| Variable | Purpose |
|---|---|
| `HRM_DATABASE_URL` | Full URL, e.g. `postgresql://user:pass@host:5432/db`. Empty means SQLite at `data/hr_management.db` |
| `HRM_DB_HOST`, `HRM_DB_PORT`, `HRM_DB_NAME`, `HRM_DB_USER`, `HRM_DB_PASSWORD`, `HRM_DB_SSLMODE` | Used when `HRM_DATABASE_URL` is empty and `HRM_DB_HOST` is set. This is how ECS injects the RDS-managed secret |
| `HRM_DATA_DIR` | Local data folder (SQLite, local files, email outbox) |

## Files

| Variable | Default | Purpose |
|---|---|---|
| `HRM_STORAGE_BACKEND` | `local` | `local` (`data/files`) or `s3` |
| `HRM_S3_BUCKET`, `HRM_S3_PREFIX` | — / `hrm` | S3 location. Objects are encrypted with SSE-S3 |
| `HRM_AWS_REGION` | `ap-south-1` | Region for S3 and SES |

## Email

| Variable | Purpose |
|---|---|
| `HRM_EMAIL_BACKEND` | `console` (default), `smtp` or `ses` |
| `HRM_EMAIL_FROM` | Sender, e.g. `Kairoz HR <hr@kairoz.com>`. Must be verified in SES |
| `HRM_SMTP_HOST`, `HRM_SMTP_PORT`, `HRM_SMTP_USERNAME`, `HRM_SMTP_PASSWORD`, `HRM_SMTP_USE_TLS` | SMTP settings |

## Optional LLM layer

| Variable | Purpose |
|---|---|
| `HRM_LLM_API_KEY` | OpenAI Responses-API-compatible key. Enables the AI review in ATS and interview scoring, generated test questions, and LLM planning in the assistant. **Secret** |
| `HRM_LLM_MODEL`, `HRM_LLM_ENDPOINT` | Model (default `gpt-4o-mini`) and a custom endpoint |
| `HRM_LLM_DAILY_BUDGET_USD`, `HRM_LLM_USER_DAILY_BUDGET_USD` | Spend caps. Above them the app quietly falls back to its rules |
| `HRM_INTERVIEW_LLM_API_KEY`, `HRM_MOCK_TEST_LLM_API_KEY`, `HRM_ASSISTANT_LLM_API_KEY` | Keys for a single feature. Each falls back to the shared key |
| `HRM_MOCK_TEST_LLM` | `off` disables generated questions |

## Rate limits

Set `HRM_RATE_LIMITS=off` to disable them all. Each limit is written `count/window_seconds`:

| Variable | Default |
|---|---|
| `HRM_LIMIT_OTP_REQUEST_EMAIL` | `3/900` |
| `HRM_LIMIT_OTP_REQUEST_IP` | `20/900` |
| `HRM_LIMIT_OTP_VERIFY_IP` | `30/900` |
| `HRM_LIMIT_STAFF_LOGIN_IP` | `30/900` |
| `HRM_LIMIT_ASSISTANT` | `120/3600` |
