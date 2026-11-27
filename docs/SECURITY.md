# Security and data protection

## Identities and sign-in

| User | Sign-in | Protection |
|---|---|---|
| Candidate | Email plus a 6-digit one-time code | The code is stored only as an HMAC hash and expires after 10 minutes. Only the newest code works, with 5 wrong guesses per code. Rate limits apply per email and per IP. Codes never appear in logs |
| Employee / HR | Unique user ID (`KZE####` / `KZH####`) plus password | Passwords are hashed with scrypt (n = 2¹⁴, r = 8, p = 1) with a per-user salt. The account locks for 15 minutes after 5 failures. Rate limits apply per IP. The same error is returned whether the user ID or the password is wrong, and unknown IDs take the same time to check |

* **Temporary passwords** (onboarding, HR reset, new HR user) are random and 12 characters long. The user must change the password before any other API call works.
* **Password rules**: at least 10 characters, letters and numbers, not containing the user ID or email, not a common password.
* **Sessions**: an HMAC-signed, HTTP-only, `SameSite=Lax` cookie, `Secure` in production, lasting 12 hours.
  - Staff sessions carry the account's `session_version`.
  - A password change, reset or deactivation increments it, which signs the account out everywhere.

## Authorisation

* Routes are grouped by audience: `api/candidate.py`, `api/employee.py` and `api/hr_*.py`. Each depends on `require_candidate`, `require_employee`, `require_hr` or `require_hr_admin`.
* Candidates only see their own applications. Ownership is checked on every call, and a foreign ID returns 404.
* Employees only see their own records. Managers can additionally decide leave for, and review, their **direct reports only**. Nobody can approve their own leave.
* Only HR can see other employees, payroll, the service desk and admin. Only `hr_admin` can create or reset administrators.
* Cross-site protection: SameSite cookies, plus an Origin check that rejects unsafe API calls from other sites.

## Sensitive data

* **PAN and bank account** are masked (`••••••1234`) in every employee view until the employee clicks "Show full details". HR sees them on the profile, and every HR profile view is written to the audit log.
* The candidate never receives the mock-test answer key, hidden coding test cases, or correct answers afterwards.
* Files (resumes, receipts, documents) are stored under random keys:
  - in a private S3 bucket with SSE-S3 encryption and a TLS-only policy, or
  - locally under `data/files` with path-traversal checks.
* The database is RDS with encryption at rest, private subnets and security groups, and TLS from the app (`sslmode=require`).
* Secrets (app key, database password, LLM key) live in Secrets Manager and are injected at runtime, never baked into the image.

## LLM safety (when enabled)

* Every piece of untrusted text (resume, answers, employee messages) is wrapped in data blocks with instructions not to follow it. Known injection phrases are neutralised.
* Protected attributes (DOB, gender, religion and similar) are removed before resume text reaches the LLM.
* Daily spend caps apply, globally and per user. Above them, the app falls back to rules.
* The assistant can only *propose* actions that change data. The employee confirms, and the services re-validate.

## Auditing

`audit_log` records:
* sign-ins and lockouts
* password changes and resets
* account activation changes
* employee creation and updates
* profile views by HR
* salary changes
* payslip generation
* leave decisions
* requests created and resolved
* policy changes
* openings created and updated
* candidate decisions

HR can read it under **Admin → Audit log**. Every email sent is in `email_log`.

## Production hardening checklist

* `HRM_ENVIRONMENT=production`. The app refuses to start without `HRM_SECRET_KEY`, never shows OTPs, enables secure cookies and HSTS, and turns off `/docs`.
* Put AWS WAF managed rules in front of the ALB.
* Turn on RDS Multi-AZ and keep deletion protection on.
* Consider column-level encryption (KMS) for PAN and bank fields if your compliance programme requires it. The masking and audit already limit who sees them.
* Define a data retention period for rejected candidates' resumes. Delete them with an S3 lifecycle rule on `hrm/resumes/` and a scheduled cleanup of old `applications`.
