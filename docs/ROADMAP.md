# Roadmap: product brief vs v2

## P0: built in v2

| Brief item | Where |
|---|---|
| AI recruitment & candidate evaluation: resume intelligence, job–candidate compatibility, AI written assessment, competency scorecard, SWOT, benchmarking, integrity monitoring | [RECRUITMENT.md](RECRUITMENT.md) |
| AI interviewer: structured, role- and competency-based, voice or text, coding | [RECRUITMENT.md](RECRUITMENT.md) |
| Employee self-service AI assistant: context-aware; checks eligibility and balance, applies leave, routes to the manager, tracks and notifies; explains payslips and policies; raises tickets, claims, documents, attendance corrections, resignations | [EMPLOYEE_PORTAL.md](EMPLOYEE_PORTAL.md) |
| Core employee management: directory, profiles, managers, status, documents, accounts with unique user IDs | [HR_PORTAL.md](HR_PORTAL.md) |
| Attendance & leave management: check-in and out, calendar, corrections, leave types, balances, approvals, holidays | [HR_PORTAL.md](HR_PORTAL.md) |

## P1: partly built

| Brief item | v2 | Next |
|---|---|---|
| Payroll intelligence | Structures, monthly payslips with LOP, PF, PT, TDS, explanations | Tax-regime engine, state-wise PT, bank payment file, payroll variance alerts |
| AI onboarding & exit agent | Resume-prefilled onboarding, automatic employee and account creation, resignation request → notice | Onboarding checklist (IT assets, induction, documents to upload), exit checklist and full & final settlement |
| Performance intelligence | 3/6/12-month check-ins, ratings and competencies, recruitment-to-performance correlation | Goals and OKRs, 360° feedback, review cycles |
| HR case resolution agent | Service desk with comments, status and side effects; assistant raises cases | Auto-triage and suggested replies from policies, SLA tracking |
| Multilingual voice for frontline staff | Browser speech in the interview | Voice mode for the assistant, Hindi and Bengali first |
| Dynamic interview follow-ups | Fixed question set per role and level | LLM follow-up question when an answer is thin |

## P2: strategic, foundations in place

| Brief item | Foundation in v2 | Next |
|---|---|---|
| Internal talent marketplace | Skill map, talent search (ready / trainable), internal role matches on the employee's Growth page | Project staffing requests, employees expressing interest |
| Workforce planning intelligence | Headcount by department, funnel, open roles vs hired | Capability forecast against the hiring plan |
| Attrition intelligence | 12-month attrition, notice tracking | Risk signals (leave patterns, review trends, tenure) |
| Employee knowledge graph | Skills, managers, reviews, recruitment evidence linked per employee | Graph queries and expertise search |
| Organisational health | Attendance, leave and review data | Pulse surveys, eNPS |

## Technical next steps

* Move background email and payroll runs to SQS + a worker (as in Job-Hunting-Agent) when volumes grow.
* Single sign-on (Google Workspace / Microsoft Entra ID) for staff alongside user IDs.
* PDF rendering for payslips and letters (currently printable HTML).
* A data-retention job for rejected candidates' resumes.
