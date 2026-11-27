# Kairoz HR Management

An AI workforce platform with HRMS at its foundation. A single portal for **Kairoz Corporation** covers three groups of people:

| Who | Signs in with | What they get |
|---|---|---|
| **Candidates** | email + one-time code at `/careers` | Apply with a resume and take each round as it unlocks: ATS screen, mock test, AI interview, selection, then onboarding |
| **Employees** | user ID (`KZE1001`) + password at `/login` | Leave, attendance, payslips, HR requests, documents, policies, growth, and a context-aware **AI HR assistant**. Managers also get **My team** |
| **HR / Admin** | user ID (`KZH1001`) + password at `/login` | Dashboard, hiring pipeline, job openings, benchmarking, onboarding, employees, leave, attendance, payroll, service desk, policies, talent search, performance and recruitment intelligence, access, email and audit logs |

```
Resume ─► ATS ≥ 75 ─► Mock test ≥ 70% ─► AI interview ≥ 75 ─► Selected ─► Onboarding form ─► Employee account
  │           │ no           │ no                │ no                (auto, or HR decides)   (prefilled from     (KZE user ID +
  │           └─ rejection   └─ rejection        └─ rejection                                resume, editable)   temp password)
  └─ every step emails the candidate automatically
```

## Quick start (VS Code)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
copy .env.example .env                  # macOS/Linux: cp .env.example .env
python -m hr_management seed-demo       # optional: demo company with employees, payslips, requests
python -m hr_management --reload        # http://127.0.0.1:8000
```

The demo seed prints its sign-ins. HR is **KZH1001 / KairozHR2026** and employees are **KZE1001–KZE1006 / Welcome2026**. KZE1001 is a manager. Full steps are in [docs/SETUP.md](docs/SETUP.md).

## Folder structure

```
HRManagement/
├── .env.example                 # every setting, documented
├── Dockerfile, docker-compose.yml, .dockerignore
├── .github/workflows/ci.yml     # tests on SQLite + PostgreSQL, image build + smoke test, CloudFormation lint
├── deploy/aws/                  # cloudformation.yaml (full stack), deploy.sh, params.example.env
├── docs/                        # architecture, setup, configuration, AWS, security, API, feature guides
├── samples/                     # test resumes (one passes the ATS screen, one does not)
├── tests/                       # pytest: pipeline rules, hiring→onboarding→employee flow, HRMS features
└── src/hr_management/
    ├── __main__.py              # CLI: serve | create-hr | seed-demo | init-db
    ├── web.py                   # FastAPI app factory, middleware, routers, startup seeding
    ├── settings.py              # HRM_* configuration
    ├── db.py, schema.py         # SQLite locally / PostgreSQL on RDS, plain SQL, idempotent schema
    ├── auth.py                  # candidate OTP, staff passwords (scrypt), signed sessions, role guards
    ├── pipeline.py              # hiring stages, pass marks, emails per outcome
    ├── notifications.py         # email templates (console / SMTP / SES) + in-app notifications
    ├── storage.py               # local disk or S3
    ├── roles.py                 # job openings (DB, seeded from catalog/roles.json)
    ├── api/                     # auth, candidate (careers), employee (/api/me), hr_recruitment, hr_people, hr_operations, pages
    ├── services/                # business logic: screening, assessment, interview, evaluation, onboarding, accounts,
    │                            #   people, leave, attendance, payroll, service_desk, documents, policies, performance,
    │                            #   talent, insights, assistant, demo, views
    ├── engines/                 # ATS, mock test and interview engines ported from Job-Hunting-Agent
    ├── templates/               # index, careers_login, careers, login, password, hr, me
    └── static/                  # css/app.css, js/*.js (no build step), img/ (Kairoz logo)
```

## Documentation

| Doc | What it covers |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Layers, request flow, data model, design rules |
| [SETUP](docs/SETUP.md) | Running locally in VS Code, demo data, tests |
| [CONFIGURATION](docs/CONFIGURATION.md) | Every `HRM_*` setting |
| [AWS_DEPLOYMENT](docs/AWS_DEPLOYMENT.md) | ECS Fargate + RDS + S3 + SES with CloudFormation |
| [RECRUITMENT](docs/RECRUITMENT.md) | ATS, mock test, AI interview, scorecard, SWOT, benchmarking, integrity |
| [ONBOARDING](docs/ONBOARDING.md) | Selection, resume-prefilled form, employee and account creation |
| [EMPLOYEE_PORTAL](docs/EMPLOYEE_PORTAL.md) | Self-service features and the AI assistant |
| [HR_PORTAL](docs/HR_PORTAL.md) | Every HR section |
| [PAYROLL](docs/PAYROLL.md) | Salary structure, payslips, deductions |
| [SECURITY](docs/SECURITY.md) | Authentication, roles, data protection |
| [API](docs/API.md) | Endpoint reference |
| [AGENTS](docs/AGENTS.md) | Conventions for contributors and coding agents |
| [ROADMAP](docs/ROADMAP.md) | Brief vs v2: built, partly built, next |
