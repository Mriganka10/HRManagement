# Employee portal (`/me`)

Employees sign in with their **user ID (`KZE####`) and password**. HR staff who also have an employee record see a link to their own employee portal.

| Section | What employees can do |
|---|---|
| **Home** | Check in and out with a live clock, see leave balances, this month's attendance, requests waiting on others, latest payslip, holidays, probation end date, and team approvals (managers) |
| **HR assistant** | Ask in plain language; the assistant acts on their behalf after they confirm (below) |
| **Leave** | Balances per type; apply with a **live eligibility check** (working days, notice, maximum days, probation, overlap, balance); history; cancel future leave |
| **Attendance** | Monthly calendar (present, late, half day, on leave, absent, holiday) with check-in and check-out times; request a correction |
| **Payslips** | Salary structure, monthly payslips with each deduction explained in plain language, printable payslip (Save as PDF) |
| **HR requests** | Raise tickets, reimbursement claims (with receipt upload), document requests, attendance corrections and resignations; talk to HR on each request; track status |
| **Profile** | Employment details (ID, designation, department, manager, joining date, probation); edit phone, address, emergency contact, LinkedIn and **skills**; PAN and bank details masked until "Show full details" |
| **Documents** | Employment, salary and address-proof certificates and experience letters issued by HR; printable |
| **Growth** | Skill coverage for their role with missing skills and training suggestions, **internal job matches**, performance check-ins |
| **Policies** | Every company policy |
| **My team** (managers only) | Approve or reject leave from direct reports, see who is in today, record 3/6/12-month check-ins |
| **Notifications** | Bell icon: leave decisions, payslips, HR replies, new team members |

## The context-aware AI assistant

`services/assistant.py`. The assistant knows the employee's designation, department, tenure, reporting manager, employment and probation status, leave balances, pending leave, open requests and latest payslip. That makes its answers specific to the person rather than generic.

### What it can do

| Ask | Tool | Changes data? |
|---|---|---|
| "How many leaves do I have left?" | `leave_balance` | no |
| "Casual leave next Monday", "sick leave today", "WFH from 12 Dec for 2 days", "half day on Friday" | `check_leave`, then the **Apply** button | yes, after confirmation |
| "Status of my leave" | `my_leave` | no |
| "Explain my last payslip", "why is my salary lower in October?", "what is PF?" | `payslip` + explanation | no |
| "What is the notice period?", "can I carry forward earned leave?" | `policy` (answers from the policy text) | no |
| "Raise a ticket: my laptop VPN is not working" | `raise_ticket` | yes, after confirmation |
| "Reimburse ₹1,200 for travel to the client" | `reimbursement` | yes, after confirmation |
| "I need an employment certificate" | `request_document` | yes, after confirmation |
| "I forgot to check in yesterday, came at 9:40" | `attendance_correction` | yes, after confirmation |
| "Status of my requests" | `track_requests` | no |
| "Who is my manager?", "when does my probation end?" | `my_profile` | no |
| "Upcoming holidays", "my attendance this month" | `holidays`, `attendance_summary` | no |
| "I want to resign" | `resign` (proposes a last working day from the notice period) | yes, after confirmation |

### How it works: plan → act → confirm

1. **Plan.** Exactly one tool is chosen for each message.
   - With `HRM_LLM_API_KEY` (or `HRM_ASSISTANT_LLM_API_KEY`) set, an LLM plans using a strict JSON schema. It receives the employee context, the last few turns and the message, all wrapped as untrusted data blocks, which guards against prompt injection.
   - Without a key, or if the LLM fails, a rule-based planner with a date parser does the same job. It understands "today", "tomorrow", "next Monday", "15 Dec", "12/12", "for 3 days", "half day" and similar phrases.
2. **Act.** Read-only tools run immediately. Write tools return a **proposed action** with a button.
3. **Confirm.** The employee clicks it. `execute` calls the same services as the UI, which re-check eligibility, balances and permissions. Nothing changes without the click.

Policy answers quote the matching policy passage. If the question is about something the policies never mention (for example "maternity leave" when no such policy exists), the assistant does **not** guess. It offers to raise an HR ticket instead.

**Arabic**: the assistant understands requests written in Arabic (dates, leave types, payslips, policies, tickets, documents, attendance corrections) and replies in Arabic when the portal is in Arabic — with or without an LLM. See [LANGUAGES.md](LANGUAGES.md). Multilingual *voice* for frontline workforces is on the roadmap.
