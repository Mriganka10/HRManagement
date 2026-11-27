# Local setup (VS Code)

## Prerequisites

* Python **3.11 or newer** (`python --version`)
* VS Code with the Python extension
* Optional: Docker Desktop, for the production-like stack with PostgreSQL

## 1. Create the environment

Open the `HRManagement` folder in VS Code, then open **Terminal → New Terminal**.

```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
#   If scripts are blocked, run once:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

When VS Code asks, choose `.venv` as the interpreter.

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

## 2. Settings

```bash
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```

The defaults work locally:
* SQLite database in `data/`
* emails printed in the terminal and saved to `data/outbox/`
* candidate sign-in codes shown on screen

If you will sign in repeatedly while testing, set `HRM_RATE_LIMITS=off`.

## 3. Sign-ins

You have two options.

**A. Demo company (recommended for a first look)**

```bash
python -m hr_management seed-demo
```

| Who | User ID | Password |
|---|---|---|
| HR administrator | `KZH1001` | `KairozHR2026` |
| Employees (KZE1001 Ananya is a manager) | `KZE1001` … `KZE1006` | `Welcome2026` |

The demo includes attendance for this month, leave requests, service requests, performance reviews and last month's payslips.

**B. Your own HR admin**

```bash
python -m hr_management create-hr --email you@kairoz.com --name "Your Name"
```

This prints a `KZH` user ID and a temporary password. You will be asked to change the password at first sign-in.

Alternatively, set `HRM_BOOTSTRAP_HR_EMAIL` in `.env`. The first start then creates the admin and prints the temporary password.

## 4. Run

```bash
python -m hr_management --reload
```

Open **http://127.0.0.1:8000**. You can also press **F5** and pick **HR Management (dev server)**, which runs it under the debugger.

## 5. Walk through the whole flow

1. **Careers**
   - Click **Careers** and sign in with any email (the code is shown on screen).
   - Apply for **Backend Developer** with `samples/strong_resume_backend_developer.txt` and 4 years of experience. It scores about 83, which passes the ATS screen.
2. **Mock test**: take it and submit. Each email appears in the terminal.
3. **Interview**: answer each question with a distinct, specific example (situation, action, result).
   - Repeated or vague answers score low, which is the correct behaviour.
   - To rehearse the onboarding part, temporarily set `HRM_INTERVIEW_PASS_SCORE=60`.
4. **Selected**: click **Complete onboarding**.
   - Skills, education, experience, phone, LinkedIn and certifications are already filled in from the resume.
   - Add your date of birth, emergency contact, PAN (`ABCDE1234F`) and bank details (`123456789012`, `HDFC0001234`), then submit.
5. **First employee sign-in**
   - The welcome email (terminal, or `data/outbox/*welcome_credentials*.html`) contains your **KZE user ID and temporary password**.
   - Sign in at `/login` and set your own password.
6. **HR side**: sign in as `KZH1001` to see the candidate, scorecard, SWOT, onboarding record and the new employee.

## 6. Tests

```bash
pytest -q
```

To run against PostgreSQL as CI does:

```bash
HRM_TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/hrm_test pytest -q
```

## Production-like stack (Docker)

```bash
docker compose up --build              # app + PostgreSQL 16 → http://localhost:8000
```

Compose creates the first HR admin `hr.admin@kairoz.local` with password `ChangeMe2026x`. Its user ID is printed in the logs.

## Reset

Stop the server and delete the `data/` folder.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: hr_management` | Activate `.venv` and run `pip install -e ".[dev]"` again |
| "Too many attempts" | Set `HRM_RATE_LIMITS=off` in `.env` for local testing |
| Fonts look different | The Google Fonts CDN is unreachable; the system fallback fonts are used |
| Voice answers don't work | Use Chrome or Edge; speech recognition needs microphone permission |
| Port 8000 busy | `python -m hr_management --port 8001` |
