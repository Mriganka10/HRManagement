# API reference

All endpoints return JSON (payslip and document views return printable HTML). Errors are `{"detail": "message"}` with a meaningful status: 400 invalid input, 401 not signed in, 403 not allowed / password change required, 404 not found or not yours, 409 conflict (wrong stage, duplicate), 410 role closed, 422 onboarding validation, 423 account locked, 429 rate limited.

Interactive docs: `/docs` (development only). Sessions are an HTTP-only cookie set by the sign-in endpoints; send requests from the same origin.

## Sign-in (`/api/auth`)

Candidate codes, staff password sign-in, password change, sign-out, current user.

| Method | Path | Endpoint |
|---|---|---|
| POST | `/api/auth/change-password` | Change Password |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Me |
| POST | `/api/auth/request-otp` | Request Otp |
| POST | `/api/auth/verify` | Verify |

## Careers – candidates (`/api/roles`, `/api/applications`)

Requires a candidate session (email code). Every call checks the application belongs to the candidate.

| Method | Path | Endpoint |
|---|---|---|
| GET | `/api/applications` | My Applications |
| POST | `/api/applications` | Apply |
| GET | `/api/applications/{application_id}` | Application Detail |
| POST | `/api/applications/{application_id}/interview/autosave` | Interview Autosave |
| POST | `/api/applications/{application_id}/interview/complete` | Interview Complete |
| POST | `/api/applications/{application_id}/interview/start` | Interview Start |
| GET | `/api/applications/{application_id}/onboarding` | Onboarding Form |
| POST | `/api/applications/{application_id}/onboarding/save` | Onboarding Save |
| POST | `/api/applications/{application_id}/onboarding/submit` | Onboarding Submit |
| POST | `/api/applications/{application_id}/test/autosave` | Test Autosave |
| POST | `/api/applications/{application_id}/test/start` | Test Start |
| POST | `/api/applications/{application_id}/test/submit` | Test Submit |
| GET | `/api/roles` | Roles |

## Employee portal (`/api/me`)

Requires a staff session linked to an employee record. Team endpoints additionally require being the approver/manager.

| Method | Path | Endpoint |
|---|---|---|
| POST | `/api/me/assistant` | Ask |
| POST | `/api/me/assistant/confirm` | Confirm |
| GET | `/api/me/attendance` | My Attendance |
| POST | `/api/me/attendance/check-in` | Check In |
| POST | `/api/me/attendance/check-out` | Check Out |
| GET | `/api/me/documents` | My Documents |
| GET | `/api/me/documents/{doc_id}` | Read Document |
| GET | `/api/me/growth` | Growth |
| GET | `/api/me/home` | Home |
| GET | `/api/me/leave` | My Leave |
| POST | `/api/me/leave` | Apply Leave |
| POST | `/api/me/leave/check` | Check Leave |
| POST | `/api/me/leave/{request_id}/cancel` | Cancel Leave |
| GET | `/api/me/notifications` | Notifications |
| POST | `/api/me/notifications/read` | Mark Read |
| GET | `/api/me/payslips` | Payslips |
| GET | `/api/me/payslips/{payslip_id}/view` | View Payslip |
| GET | `/api/me/policies` | Policy List |
| GET | `/api/me/profile` | Profile |
| PUT | `/api/me/profile` | Update Profile |
| GET | `/api/me/requests` | My Requests |
| POST | `/api/me/requests` | Create Request |
| GET | `/api/me/requests/{request_id}` | Request Detail |
| POST | `/api/me/requests/{request_id}/cancel` | Request Cancel |
| POST | `/api/me/requests/{request_id}/comments` | Request Comment |
| GET | `/api/me/team` | Team |
| POST | `/api/me/team/leave/{request_id}/decision` | Team Decide |
| POST | `/api/me/team/{employee_id}/reviews` | Team Review |

## HR – recruitment (`/api/hr/recruitment`)

Requires an HR session.

| Method | Path | Endpoint |
|---|---|---|
| GET | `/api/hr/recruitment/applications/{application_id}` | Detail |
| POST | `/api/hr/recruitment/applications/{application_id}/decision` | Decision |
| GET | `/api/hr/recruitment/applications/{application_id}/resume` | Resume |
| GET | `/api/hr/recruitment/benchmark/{role_key}` | Benchmark |
| GET | `/api/hr/recruitment/emails` | Email Log |
| GET | `/api/hr/recruitment/onboarding` | Onboarding Tracker |
| GET | `/api/hr/recruitment/openings` | Openings |
| POST | `/api/hr/recruitment/openings` | Create Opening |
| PUT | `/api/hr/recruitment/openings/{key}` | Update Opening |
| GET | `/api/hr/recruitment/overview` | Overview |

## HR – people & operations (`/api/hr`)

Requires an HR session (`hr` or `hr_admin`). Creating/resetting administrators requires `hr_admin`.

| Method | Path | Endpoint |
|---|---|---|
| GET | `/api/hr/accounts` | Account List |
| POST | `/api/hr/accounts` | Create Hr Account |
| POST | `/api/hr/accounts/{account_id}/active` | Set Active |
| POST | `/api/hr/accounts/{account_id}/reset-password` | Reset Password |
| GET | `/api/hr/attendance` | Attendance Day |
| GET | `/api/hr/attendance/{employee_id}` | Attendance Month |
| GET | `/api/hr/audit` | Audit Log |
| GET | `/api/hr/dashboard` | Dashboard |
| GET | `/api/hr/employees` | Employees |
| POST | `/api/hr/employees` | Add Employee |
| GET | `/api/hr/employees/{employee_id}` | Employee |
| PUT | `/api/hr/employees/{employee_id}` | Update Employee |
| POST | `/api/hr/employees/{employee_id}/documents` | Generate Document |
| POST | `/api/hr/employees/{employee_id}/reviews` | Save Review |
| POST | `/api/hr/employees/{employee_id}/salary` | Set Salary |
| GET | `/api/hr/holidays` | Holidays |
| POST | `/api/hr/holidays` | Add Holiday |
| DELETE | `/api/hr/holidays/{holiday_id}` | Delete Holiday |
| GET | `/api/hr/leave` | Leave Queue |
| PUT | `/api/hr/leave/types/{type_id}` | Update Leave Type |
| POST | `/api/hr/leave/{request_id}/decision` | Decide Leave |
| GET | `/api/hr/notifications` | Hr Notifications |
| POST | `/api/hr/notifications/read` | Hr Notifications Read |
| GET | `/api/hr/payroll` | Payroll Overview |
| POST | `/api/hr/payroll/run` | Run Payroll |
| GET | `/api/hr/payslips/{payslip_id}/view` | View Payslip |
| GET | `/api/hr/performance/due` | Due |
| GET | `/api/hr/performance/intelligence` | Intelligence |
| GET | `/api/hr/policies` | Policy List |
| POST | `/api/hr/policies` | Policy Create |
| DELETE | `/api/hr/policies/{policy_id}` | Policy Delete |
| PUT | `/api/hr/policies/{policy_id}` | Policy Update |
| GET | `/api/hr/requests` | Requests |
| GET | `/api/hr/requests/{request_id}` | Request Detail |
| GET | `/api/hr/requests/{request_id}/attachment` | Request Attachment |
| POST | `/api/hr/requests/{request_id}/comments` | Request Comment |
| POST | `/api/hr/requests/{request_id}/resolve` | Resolve Request |
| POST | `/api/hr/talent/search` | Talent Search |
| GET | `/api/hr/talent/skills` | Skill Map |

## Other

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Load-balancer health check (also checks the database) |
| GET | `/`, `/careers/login`, `/careers`, `/login`, `/password`, `/hr`, `/me` | HTML pages (redirect to the right page for the signed-in user) |

## Examples

```bash
# Staff sign-in (cookie jar)
curl -c jar -H 'Content-Type: application/json' -d '{"user_id":"KZE1002","password":"..."}' http://127.0.0.1:8000/api/auth/login

# Check leave eligibility
curl -b jar -H 'Content-Type: application/json' -d '{"leave_type":"CL","start_date":"2026-12-15"}' http://127.0.0.1:8000/api/me/leave/check

# Ask the assistant; confirm the proposed action it returns
curl -b jar -H 'Content-Type: application/json' -d '{"message":"casual leave on 15 Dec"}' http://127.0.0.1:8000/api/me/assistant
curl -b jar -H 'Content-Type: application/json' -d '{"action":{...action from the previous reply...}}' http://127.0.0.1:8000/api/me/assistant/confirm
```
