# HR Management – Agentic Hiring Pipeline (prototype v1)

A web tool that takes candidates from resume upload through to the end of the interview, emailing them at every step:

```
Sign in with email code
      │
Upload resume for a role ──► ATS score ≥ 75 ? ──no──► rejection email (stop)
      │ yes → "You're shortlisted for the mock test" email
Mock test (timed MCQ for the role) ──► score ≥ 70% ? ──no──► rejection email (stop)
      │ yes → "You've qualified for the interview" email
Mock interview (role questions, voice or text, coding for tech roles) ──► score ≥ 75 ? ──no──► rejection email
      │ yes
"Thank you for attending – next steps soon" email   →  HR board shows "Cleared – next steps"
```

A score equal to the pass mark counts as a pass. All three pass marks can be changed in `.env`.

The ATS scorer, mock-test builder and interview evaluator are ported from the **Job-Hunting-Agent** project
(`src/hr_management/engines/`). Everything works without an LLM key; adding one switches on an extra AI review layer.

---

## Folder structure

```
HRManagement/
├── .env.example              # every setting, documented – copy to .env
├── .vscode/                  # launch.json (run/debug server & tests) + settings.json
├── pyproject.toml            # package + dependencies (src layout)
├── requirements.txt
├── samples/                  # test resumes: one that passes the ATS screen, one that fails
├── tests/                    # pytest: pipeline rules + full end-to-end hiring flow
└── src/hr_management/
    ├── __main__.py           # `python -m hr_management` → starts uvicorn
    ├── web.py                # FastAPI app factory: middleware, error handlers, routers, static files
    ├── settings.py           # HRM_* settings from env / .env (thresholds, email, DB, secrets)
    ├── db.py                 # SQLite locally / PostgreSQL in prod, plain SQL, compare-and-set stage changes
    ├── auth.py               # email OTP + signed HTTP-only session cookie, HR role via HRM_HR_EMAILS
    ├── pipeline.py           # ★ hiring rules: stages, allowed moves, pass marks, which email each outcome sends
    ├── notifications.py      # email templates + sender (console/outbox locally, SMTP for real)
    ├── roles.py              # open roles loader
    ├── catalog/roles.json    # open roles: title, JD, required skills, experience (HR edits this)
    ├── services/             # business logic, called by the API routes
    │   ├── screening.py      #   stage 1: resume upload + ATS score against the role's JD
    │   ├── assessment.py     #   stage 2: build/resume/autosave/grade the mock test (server-side timer)
    │   ├── interview.py      #   stage 3: build questions, autosave answers, evaluate
    │   └── views.py          #   what candidates vs HR are allowed to see
    ├── api/                  # HTTP routers, one per audience
    │   ├── auth.py           #   /api/auth/*  request-otp, verify, logout, me
    │   ├── candidate.py      #   /api/roles, /api/applications/*  (test & interview endpoints)
    │   ├── hr.py             #   /api/hr/*  board, candidate detail, resume download, email log
    │   └── pages.py          #   /login, /app, /hr  HTML pages
    ├── engines/              # ported from Job-Hunting-Agent (keep close to originals)
    │   ├── resume.py, ats*.py                 # resume parsing + deterministic ATS score
    │   ├── mock_test*.py                      # question bank, test builder, grader
    │   ├── interview_*.py, coding_problems.py # question selection, coding problems, evaluator
    │   ├── llm_client.py, guardrails.py       # optional LLM layer, budgets, rate limits, prompt-injection guard
    │   └── ops_db.py, metrics.py              # small adapters onto this project's db
    ├── templates/            # login.html, app.html (candidate), hr.html (HR board)
    └── static/               # css/app.css, js/common.js, login.js, app.js, hr.js (no build step)
```

`data/` is created on first run. It holds the SQLite database, uploaded resumes and `outbox/` with a copy of every email. It's git-ignored because it contains candidate data.

---

## Run it locally in VS Code

**Prerequisite:** Python 3.11 or newer (`python --version`).

1. Open the `HRManagement` folder in VS Code, then open a terminal (**Terminal → New Terminal**).

2. Create and activate a virtual environment:

   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   # If PowerShell blocks the script, run this once first:
   #   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   When VS Code asks, choose this `.venv` as the interpreter.

3. Install the project (editable) and the test tools:

   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. Create your settings file:

   ```bash
   # Windows
   copy .env.example .env
   # macOS / Linux
   cp .env.example .env
   ```

   For local use, the defaults are enough. Optionally set `HRM_HR_EMAILS` to the email you'll use as HR.

5. Start the server:

   ```bash
   python -m hr_management --reload
   ```

   Then open **http://127.0.0.1:8000**. You can also press **F5** and pick "HR Management (dev server)" to run it with the debugger.

6. Run the tests in a second terminal:

   ```bash
   pytest -q
   ```

### Try the whole flow

1. Sign in with any email, e.g. `candidate@example.com`. In development the 6-digit code shows on the login screen and is also printed in the terminal.
2. Pick **Backend Developer** and upload `samples/strong_resume_backend_developer.txt` with 4 years of experience. It scores about 83 and unlocks the mock test.
   - To see the rejection path, upload `samples/weak_resume.txt` instead.
3. Take the mock test, then the interview. Each email prints in the terminal and is saved as HTML in `data/outbox/`, so you can open it in a browser.
4. Sign out and sign in as `hr@example.com` (the default HR email) to see the hiring board, candidate details, the interview transcript, integrity flags and the email log.

To start over, stop the server and delete the `data/` folder.

### Send real emails

In `.env`, set:

```
HRM_EMAIL_BACKEND=smtp
HRM_SMTP_HOST=smtp.gmail.com
HRM_SMTP_PORT=587
HRM_SMTP_USERNAME=you@gmail.com
HRM_SMTP_PASSWORD=<app password>
HRM_SMTP_FROM=you@gmail.com
```

AWS SES SMTP credentials also work.

---

## API overview

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/api/auth/request-otp` | anyone | email a 6-digit sign-in code |
| POST | `/api/auth/verify` | anyone | verify code, set session cookie |
| GET | `/api/roles` | candidate | open roles + pass marks |
| GET/POST | `/api/applications` | candidate | list / apply (multipart: role_key, full_name, experience_years, phone, resume) |
| POST | `/api/applications/{id}/test/start` · `/autosave` · `/submit` | candidate | mock test |
| POST | `/api/applications/{id}/interview/start` · `/autosave` · `/complete` | candidate | mock interview |
| GET | `/api/hr/overview` · `/api/hr/applications/{id}` · `/resume` · `/api/hr/emails` | HR | board, detail, resume, email log |
| GET | `/health` | anyone | liveness for the load balancer |

The interactive API docs are at `/docs`.

## Integrity and production notes

- **Mock test answer key:** it never leaves the server. Candidates see their score and topic breakdown, never the correct answers, so the question bank can be reused.
- **Test timer:** the server times the test. Answers autosave as the candidate goes. Once time is up (plus `HRM_TEST_GRACE_SECONDS`), only the saved answers count, and the test is closed even if the candidate never presses Submit.
- **Interview code:** submitted code is reviewed statically and never run on the server. Hidden coding test cases are not sent to the browser.
- **Behaviour signals:** tab switches, copy attempts and pastes are recorded and shown to HR as signals; they never decide pass or fail.
- **Stage changes:** each change is compare-and-set, so a double click or a second tab can't take a test twice or send duplicate emails.
- **Email outages:** emails go out after the response, in the background. A mail outage is logged and shown on the HR board but never blocks the pipeline.
- **Production settings:** `HRM_SECRET_KEY` (random), `HRM_DEV_RETURN_OTP=false`, `HRM_COOKIE_SECURE=true`, a PostgreSQL `HRM_DATABASE_URL` (install the `postgres` extra), and SMTP or SES email.

## Next steps (not in v1)

- Dockerfile and AWS deployment (ECS + RDS + S3 + SES), following the Job-Hunting-Agent setup.
- HR actions on the board: manual override, schedule an HR round, send an offer, onboarding checklist.
- Move uploaded resumes to S3, and roles from `roles.json` to an HR admin screen.
