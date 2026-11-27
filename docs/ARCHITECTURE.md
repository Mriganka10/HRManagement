# Architecture

## One portal, three audiences

```
                         ┌──────────────── Kairoz HR Management (FastAPI, one container) ────────────────┐
 Candidate ──/careers──► │ api/candidate.py ─┐                                                            │
 Employee  ──/me──────►  │ api/employee.py  ─┼─► services/*  ──► engines/* (ATS, mock test, interview)   │──► PostgreSQL (RDS)
 HR / Admin ─/hr──────►  │ api/hr_*.py      ─┘        │                                                   │──► S3 (files)
                         │ api/auth.py, api/pages.py   └──► notifications (email + in-app), storage, db   │──► SES (email)
                         └────────────────────────────────────────────────────────────────────────────────┘
```

* **Pages** are static HTML templates (`templates/`) with plain JavaScript (`static/js/`) that calls JSON APIs. There is no front-end build step.
* **API routers** (`api/`) only handle HTTP: they parse input, check who is signed in, call a service and return JSON. They are split by audience, so permission mistakes are easy to spot.
* **Services** (`services/`) hold all business rules. Each one is a plain Python module with functions; there are no classes or DI containers. Services raise `ServiceError(message, status)`, which the app turns into JSON errors.
* **Engines** (`engines/`) are the ATS, mock-test and interview engines ported from Job-Hunting-Agent. Keep them close to the originals so fixes can move both ways. `ops_db.py` and `metrics.py` adapt them to this project's database.
* **Infrastructure modules** each wrap one external dependency behind a small interface so the backend can be swapped by configuration: `db.py` (SQLite or PostgreSQL), `storage.py` (local or S3) and `notifications.py` (console, SMTP or SES).

## Layer rules

1. Routes call services. Services call `db`, `storage`, `notifications` and engines. Engines never import services.
2. Every state change that matters goes through a **compare-and-set** update, e.g. `db.transition_stage(id, from_stages, to)` or `db.update(..., where="status = 'pending'")`. Double clicks, two tabs or two ECS tasks can therefore never approve twice, grade twice or create two employees.
3. Every important action is written to `audit_log` with `db.audit(actor, action, entity, id, detail)`.
4. Emails never break a workflow. `notifications.send` logs failures to `email_log` and returns `False`.
5. Schema changes are **additive only**: new tables go in `schema.statements`, new columns in `schema.ADDITIVE_COLUMNS`. The schema is applied on every start, which is idempotent.

## Data model (main tables)

| Area | Tables |
|---|---|
| Candidates | `users` (candidate emails), `otp_codes`, `applications`, `mock_tests`, `interviews`, `pipeline_events`, `onboarding`, `email_log` |
| Hiring setup | `job_openings` |
| People | `accounts` (unique user IDs, password hashes, roles), `employees`, `documents` |
| Time | `leave_types`, `leave_requests`, `holidays`, `attendance` |
| Pay | `salary_structures`, `payslips` |
| Service desk & content | `service_requests`, `request_comments`, `policies` |
| Growth | `performance_reviews` |
| Platform | `notifications`, `audit_log`, `rate_events`, `llm_usage` |

`applications` → `onboarding` → `employees` → `accounts` is the chain from candidate to employee. `employees.application_id` keeps the link so recruitment scores can be compared with on-the-job performance (see recruitment intelligence in [RECRUITMENT.md](RECRUITMENT.md)).

## Hiring state machine

Defined in `pipeline.py`:

```
screening ─► ats_rejected
          └► test_pending ─► test_in_progress ─► test_rejected
                                             └► interview_pending ─► interview_in_progress ─► interview_rejected
                                                                                           ├► selected            (HRM_AUTO_SELECT=true)
                                                                                           └► interview_passed ─► selected | not_selected (HR)
                                                              selected ─► hired (onboarding submitted) | not_selected
```

`pipeline.STAGE_EMAILS` maps the stage an application lands in to the email it sends.

## Request lifecycle (example: an employee applies for leave)

1. `me.js` posts to `/api/me/leave`.
2. `api/employee.py` resolves the signed-in employee with `auth.require_employee`.
3. `services/leave.apply` re-runs `check_eligibility`, which checks notice, maximum days, probation, overlap and balance. It then inserts the request with the approver set to the employee's manager (or HR if there is none), notifies the approver in-app and by email, and writes an audit entry.
4. The manager approves from **My team** in their own employee portal. `leave.decide` checks they are the approver, compare-and-sets `pending → approved`, marks those days as on leave in attendance and notifies the employee.

## The agentic assistant

`services/assistant.py`: **plan → act → confirm.** The planner is an LLM with a strict JSON schema when a key is configured, and a rule-based parser with date understanding otherwise. Read-only tools run immediately. Tools that change data come back as a proposed action that the employee confirms with a button. `execute` then calls the same services the UI uses, which re-validate everything. Details are in [EMPLOYEE_PORTAL.md](EMPLOYEE_PORTAL.md).

## Scaling on AWS

The app is stateless: sessions are signed cookies, files live in S3 and data in RDS. Any number of ECS tasks can run behind the load balancer. Background email is sent in-process after the response (FastAPI `BackgroundTasks`). If volumes grow, move sending to SQS plus a worker, as the Job-Hunting-Agent worker does; the `notifications` interface stays the same.
