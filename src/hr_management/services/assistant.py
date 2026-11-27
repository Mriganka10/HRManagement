"""Agentic, context-aware Employee Assistant.

The assistant knows who is asking (designation, department, tenure, reporting manager,
probation/employment status, leave balances, open requests, latest payslip) and acts through
the same services the portal uses — it never touches the database directly.

Flow for every message:
1. **Plan**: pick one tool + arguments. With an LLM key configured (HRM_LLM_API_KEY) the LLM
   plans using a strict JSON schema; otherwise (or if the LLM fails) a rule-based planner
   with a small date parser is used. Both produce the same plan shape.
2. **Act**: read-only tools run immediately (balances, eligibility, payslip explanation,
   policy answers, request tracking...). Tools that change data (apply leave, raise ticket,
   reimbursement, document request, attendance correction, resignation) are returned as a
   *proposed action* the employee must confirm with a button — human in the loop.
3. **Confirm**: ``execute`` runs the confirmed action through the service layer, which
   re-validates everything (eligibility, balances, permissions).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from .. import db
from ..engines.llm_client import call_json, enabled as llm_enabled
from . import ServiceError, attendance, leave, payroll, people, policies, service_desk

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
WEEKDAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
LEAVE_WORDS = {"SL": r"\bsick|unwell|fever|ill\b|doctor|medical", "WFH": r"\bwfh\b|work(ing)? from home|remote", "EL": r"\bearned|privilege|vacation|annual leave|\bel\b|holiday trip",
               "LWP": r"unpaid|without pay|\blwp\b", "CL": r"\bcasual|\bcl\b|personal"}
TICKET_HINTS = (
    ("IT & access", r"laptop|vpn|access|password|e-?mail|wifi|system|software|login"),
    ("Payroll", r"salary|payslip|pay\b|tds|tax|pf\b"),
    ("Benefits & insurance", r"insurance|medical|health|benefit"),
    ("Leave & attendance", r"leave|attendance|check.?in"),
    ("Policy question", r"policy|rule"),
)
WRITE_TOOLS = {"apply_leave", "raise_ticket", "reimbursement", "request_document", "attendance_correction", "resign"}
TOOLS = ["leave_balance", "check_leave", "apply_leave", "my_leave", "payslip", "policy", "raise_ticket", "reimbursement",
         "request_document", "attendance_correction", "track_requests", "my_profile", "holidays", "attendance_summary",
         "resign", "answer"]


# ---------------------------------------------------------------------------- context

def context(employee: dict) -> dict:
    emp = people.get(employee["id"])
    tenure = (date.today() - date.fromisoformat(emp["date_of_joining"])).days
    pending = service_desk.list_for(employee_id=emp["id"], status="active")
    slip = db.fetch_one("SELECT period, net_pay FROM payslips WHERE employee_id = ? ORDER BY period DESC LIMIT 1", (emp["id"],))
    return {
        "name": emp["full_name"], "employee_code": emp["employee_code"], "designation": emp["designation"],
        "department": emp["department"], "status": emp["status"], "probation_end": emp.get("probation_end"),
        "date_of_joining": emp["date_of_joining"], "tenure": f"{tenure // 365} years {(tenure % 365) // 30} months",
        "manager": emp.get("manager_name") or "HR (no reporting manager assigned)",
        "leave_balances": {b["code"]: b["available"] for b in leave.balances(emp)},
        "open_requests": [f"{r['ref']} {r['kind_label']}: {r['subject']} ({r['status']})" for r in pending[:5]],
        "pending_leave": [f"{r['leave_name']} {r['start_date']}..{r['end_date']}" for r in leave.list_requests(employee_id=emp["id"], status="pending")[:5]],
        "latest_payslip": dict(slip) if slip else None, "today": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------- date parsing

def _parse_day(token: str, today: date) -> date | None:
    token = token.strip().lower().replace(",", " ")
    if token in {"today"}:
        return today
    if token in {"tomorrow", "tmrw", "tomorow"}:
        return today + timedelta(days=1)
    if token == "day after tomorrow":
        return today + timedelta(days=2)
    m = re.match(r"(?:next\s+|this\s+|coming\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", token)
    if m:
        ahead = (WEEKDAYS[m.group(1)] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", token)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", token)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        year = year + 2000 if year < 100 else year
        return date(year, int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3})[a-z]*(?:\s+(\d{4}))?", token) or None
    if m and m.group(2) in MONTHS:
        year = int(m.group(3)) if m.group(3) else today.year
        result = date(year, MONTHS[m.group(2)], int(m.group(1)))
        return result if m.group(3) or result >= today - timedelta(days=7) else result.replace(year=year + 1)
    m = re.match(r"([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?", token)
    if m and m.group(1) in MONTHS:
        year = int(m.group(3)) if m.group(3) else today.year
        result = date(year, MONTHS[m.group(1)], int(m.group(2)))
        return result if m.group(3) or result >= today - timedelta(days=7) else result.replace(year=year + 1)
    return None


DAY_PATTERN = (r"(?:day after tomorrow|today|tomorrow|tmrw|(?:next |this |coming )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
               r"|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[a-z]{3,9}(?:\s+\d{4})?"
               r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?)")


def parse_dates(text: str, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or date.today()
    lowered = text.lower()
    found = []
    for match in re.finditer(DAY_PATTERN, lowered):
        try:
            day = _parse_day(match.group(0), today)
        except ValueError:
            day = None
        if day:
            found.append(day)
    if not found:
        return None, None
    start = found[0]
    end = found[1] if len(found) > 1 else start
    span = re.search(r"for\s+(\d+)\s+(?:working\s+)?days?", lowered)
    if span and len(found) == 1:
        remaining, end = int(span.group(1)) - 1, start
        while remaining > 0:
            end += timedelta(days=1)
            if end.weekday() < 5:
                remaining -= 1
    return start, max(start, end)


# ---------------------------------------------------------------------------- planning

def _leave_type(text: str) -> str:
    lowered = text.lower()
    for code, pattern in LEAVE_WORDS.items():
        if re.search(pattern, lowered):
            return code
    return "CL"


def _amount(text: str) -> float | None:
    m = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees|rs\b|inr)", text.lower())
    if not m:
        return None
    return float((m.group(1) or m.group(2)).replace(",", ""))


def plan_rules(message: str) -> dict:
    text = message.strip()
    t = text.lower()
    start, end = parse_dates(t)
    half = bool(re.search(r"half[\s-]?day", t))
    if re.search(r"resign|quit (my|the) job|put (in|down) my papers|leaving the company", t) and not re.search(r"policy|how|what", t):
        return {"tool": "resign", "args": {"last_working_day": start.isoformat() if start else None, "description": text}}
    if re.search(r"\bpolic(y|ies)\b|\brules?\b|\bentitle", t) or (re.search(r"^(what|how|can|is|are|do|does|when|why)\b", t) and not re.search(
            r"my (leave|balance|payslip|salary|request|manager|attendance|probation|profile|designation|department|joining)|i (need|want|forgot)|apply|raise|reimburse .*\d", t)
            and not start and _amount(t) is None and not re.search(r"payslip|deduction|\bpf\b|\btds\b|holiday|leave|manager|net pay|salary", t)):
        return {"tool": "policy", "args": {"query": text}}
    if re.search(r"forgot to (check|punch|mark)|attendance correction|correct (my )?attendance|missed (my )?(check|punch)", t):
        times = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.sub(DAY_PATTERN, " ", t))
        clock = []
        for h, mnt, ampm in times:
            hour = int(h) % 12 + (12 if ampm == "pm" else 0) if ampm else int(h)
            if 0 <= hour < 24:
                clock.append(f"{hour:02d}:{mnt or '00'}")
        return {"tool": "attendance_correction", "args": {"date": (start or date.today() - timedelta(days=1)).isoformat(),
                                                           "check_in": clock[0] if clock else "09:30", "check_out": clock[1] if len(clock) > 1 else "18:30",
                                                           "description": text}}
    if re.search(r"reimburs|expense claim|claim (for|my)|\bclaim\b.*(₹|rs|rupees|inr)", t):
        category = next((c for c in service_desk.REIMBURSEMENT_CATEGORIES if c.split()[0].lower() in t), "Other")
        return {"tool": "reimbursement", "args": {"amount": _amount(t), "category": category, "description": text}}
    if re.search(r"certificate|experience letter|address proof|salary letter|employment letter", t):
        doc = next((d for d in service_desk.DOCUMENT_TYPES if d.split()[0].lower() in t), "Employment certificate")
        return {"tool": "request_document", "args": {"document_type": doc}}
    if re.search(r"payslip|pay slip|salary slip|deduction|net pay|\bpf\b|provident|professional tax|\btds\b|why (is|was) my salary|in.?hand", t):
        month = next((m for m in MONTHS if re.search(rf"\b{m}[a-z]*\b", t)), None)
        period = None
        if month:
            year = date.today().year if MONTHS[month] <= date.today().month else date.today().year - 1
            period = f"{year}-{MONTHS[month]:02d}"
        elif "last month" in t:
            first = date.today().replace(day=1) - timedelta(days=1)
            period = f"{first.year}-{first.month:02d}"
        return {"tool": "payslip", "args": {"period": period}}
    if re.search(r"leave|day off|days off|\boff\b|\bwfh\b|work from home|vacation|sick|half[\s-]?day", t) and not re.search(r"policy|rule|allowed|how many .* (can|per year)|carry", t):
        if re.search(r"balance|how many|left|remaining|available", t):
            return {"tool": "leave_balance", "args": {}}
        if re.search(r"status|my leaves|pending|approved\?|history", t) and not start:
            return {"tool": "my_leave", "args": {}}
        if start:
            return {"tool": "check_leave", "args": {"leave_type": _leave_type(t), "start_date": start.isoformat(),
                                                    "end_date": end.isoformat() if end else start.isoformat(), "half_day": half, "description": text}}
        return {"tool": "answer", "args": {"text": "Sure — which dates? For example: “casual leave on 12 Dec”, “sick leave today”, or “WFH from next Monday for 2 days”."}}
    if re.search(r"track|status of|my requests|pending requests|open tickets|my tickets", t):
        return {"tool": "track_requests", "args": {}}
    if re.search(r"raise (a |an )?(ticket|complaint|issue)|(laptop|access|vpn|email|insurance|salary) (issue|problem|not working)|complain", t):
        category = next((name for name, pattern in TICKET_HINTS if re.search(pattern, t)), "Other")
        return {"tool": "raise_ticket", "args": {"category": category, "subject": text[:90], "description": text}}
    if re.search(r"holiday", t):
        return {"tool": "holidays", "args": {}}
    if re.search(r"attendance|present|late|check.?in", t):
        return {"tool": "attendance_summary", "args": {}}
    if re.search(r"(my|who is my) (manager|designation|department|profile|joining|probation)|who am i|employee id", t):
        return {"tool": "my_profile", "args": {}}
    return {"tool": "policy", "args": {"query": text}}


_PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["tool", "args"],
    "properties": {
        "tool": {"type": "string", "enum": TOOLS},
        "args": {"type": "object", "additionalProperties": False,
                 "required": ["leave_type", "start_date", "end_date", "half_day", "period", "query", "category", "subject",
                              "description", "amount", "document_type", "date", "check_in", "check_out", "last_working_day", "text"],
                 "properties": {k: {"type": ["string", "null"]} for k in ("leave_type", "start_date", "end_date", "period", "query", "category",
                                                                          "subject", "description", "document_type", "date", "check_in",
                                                                          "check_out", "last_working_day", "text")}
                 | {"half_day": {"type": ["boolean", "null"]}, "amount": {"type": ["number", "null"]}}},
    },
}

_PLANNER = """You are the planner for an HR employee assistant. Choose exactly ONE tool for the employee's latest message and fill its args
(unused args = null). Dates must be ISO YYYY-MM-DD, resolved relative to "today" in the context. Leave types: CL casual, SL sick,
EL earned/vacation, WFH work from home, LWP unpaid. Tools:
leave_balance; check_leave(leave_type,start_date,end_date,half_day) — use whenever the employee wants leave on specific dates;
my_leave; payslip(period YYYY-MM or null for latest) — salary, deductions, PF, tax questions; policy(query) — any rule/policy question;
raise_ticket(category,subject,description); reimbursement(category,amount,description); request_document(document_type: Employment certificate|
Salary certificate|Address proof letter|Experience letter); attendance_correction(date,check_in HH:MM,check_out HH:MM,description);
track_requests; my_profile; holidays; attendance_summary; resign(last_working_day,description) — only if they clearly want to resign;
answer(text) — only for greetings or when you must ask a clarifying question (e.g. dates missing)."""


def plan(message: str, ctx: dict, history: list[dict]) -> dict:
    if llm_enabled(("HRM_ASSISTANT_LLM_API_KEY", "HRM_LLM_API_KEY")):
        recent = "\n".join(f"{h.get('role')}: {str(h.get('text'))[:300]}" for h in history[-6:])
        result = call_json(
            "employee_assistant", instructions=_PLANNER,
            data={"context": json.dumps(ctx, default=str), "conversation": recent, "message": message},
            schema=_PLAN_SCHEMA, schema_name="assistant_plan", key_envs=("HRM_ASSISTANT_LLM_API_KEY", "HRM_LLM_API_KEY"),
            max_output_tokens=400, timeout=15, user_email=ctx.get("employee_code", ""),
        )
        if isinstance(result, dict) and result.get("tool") in TOOLS:
            args = {k: v for k, v in (result.get("args") or {}).items() if v not in (None, "")}
            return {"tool": result["tool"], "args": args, "planner": "llm"}
    return {**plan_rules(message), "planner": "rules"}


# ---------------------------------------------------------------------------- acting

def _fmt_dates(start: str, end: str) -> str:
    return start if start == end else f"{start} to {end}"


def respond(employee: dict, message: str, history: list[dict] | None = None) -> dict:
    message = (message or "").strip()[:1000]
    if not message:
        raise ServiceError("Type a question.")
    emp = people.get(employee["id"])
    ctx = context(emp)
    step = plan(message, ctx, history or [])
    tool, args = step["tool"], step.get("args") or {}
    out: dict[str, Any] = {"tool": tool, "planner": step["planner"], "reply": "", "cards": [], "action": None, "suggestions": []}

    if tool == "leave_balance":
        rows = leave.balances(emp)
        out["reply"] = "Here is your leave balance for this year:"
        out["cards"].append({"type": "table", "columns": ["Leave", "Available", "Used", "Pending"],
                             "rows": [[b["name"], f"{b['available']:g}", f"{b['used']:g}", f"{b['pending']:g}"] for b in rows]})
        out["suggestions"] = ["Apply casual leave tomorrow", "What is the leave policy?"]
    elif tool in {"check_leave", "apply_leave"}:
        start = args.get("start_date")
        if not start:
            out["reply"] = "Which dates do you need? For example “sick leave today” or “casual leave on 12 Dec”."
        else:
            end = args.get("end_date") or start
            check = leave.check_eligibility(emp, args.get("leave_type") or "CL", start, end, half_day=bool(args.get("half_day")))
            name = (check.get("leave_type") or {}).get("name", "Leave")
            if check["eligible"]:
                approver = ctx["manager"]
                out["reply"] = (f"You're eligible for {name} on {_fmt_dates(check['start_date'], check['end_date'])} "
                                f"({check['days']:g} working day(s)). You'll have {check['balance']['available'] - check['days']:g} day(s) left. "
                                f"It will go to {approver} for approval. Shall I apply?")
                out["action"] = {"tool": "apply_leave", "label": f"Apply {name}", "args": {
                    "leave_type": check["leave_type"]["code"], "start_date": check["start_date"], "end_date": check["end_date"],
                    "half_day": check["half_day"], "reason": args.get("description") or message}}
            else:
                out["reply"] = f"I can't apply {name} for {_fmt_dates(check.get('start_date', start), check.get('end_date', end))} yet:"
                out["cards"].append({"type": "list", "items": check["problems"]})
                out["suggestions"] = ["Show my leave balance", "What is the leave policy?"]
    elif tool == "my_leave":
        rows = leave.list_requests(employee_id=emp["id"], limit=8)
        out["reply"] = "Your recent leave requests:" if rows else "You have no leave requests yet."
        if rows:
            out["cards"].append({"type": "table", "columns": ["Leave", "Dates", "Days", "Status"],
                                 "rows": [[r["leave_name"], _fmt_dates(r["start_date"], r["end_date"]), f"{r['days']:g}", r["status"]] for r in rows]})
    elif tool == "payslip":
        period = args.get("period")
        slip = (db.fetch_one("SELECT * FROM payslips WHERE employee_id = ? AND period = ?", (emp["id"], period)) if period else None) or \
            db.fetch_one("SELECT * FROM payslips WHERE employee_id = ? ORDER BY period DESC LIMIT 1", (emp["id"],))
        if not slip:
            out["reply"] = "No payslip has been generated for you yet. Payslips appear here after HR runs payroll for the month."
        else:
            out["reply"] = f"Your payslip for {slip['period']}: net pay {payroll.inr(slip['net_pay'])}."
            out["cards"].append({"type": "list", "items": payroll.explain(slip)})
            out["cards"].append({"type": "link", "label": "Open payslip", "href": f"/api/me/payslips/{slip['id']}/view"})
    elif tool == "policy":
        hits = policies.search(args.get("query") or message)
        if not hits or hits[0]["score"] < 1.0:
            out["reply"] = ("I couldn't find that in the company policies. I can raise an HR ticket so someone from HR answers you.")
            out["action"] = {"tool": "raise_ticket", "label": "Ask HR", "args": {"category": "Policy question", "subject": message[:90], "description": message}}
        else:
            out["reply"] = f"From the {hits[0]['policy']}: {hits[0]['passage']}"
            if len(hits) > 1:
                out["cards"].append({"type": "list", "items": [f"{h['policy']}: {h['passage']}" for h in hits[1:]]})
    elif tool == "raise_ticket":
        out["reply"] = "I'll raise this as an HR ticket. Check the details and confirm."
        out["action"] = {"tool": "raise_ticket", "label": "Raise ticket", "args": {
            "category": args.get("category") or "Other", "subject": args.get("subject") or message[:90], "description": args.get("description") or message}}
    elif tool == "reimbursement":
        amount = args.get("amount")
        if not amount:
            out["reply"] = "How much is the claim? For example “reimburse ₹1,200 for travel to the client office”."
        else:
            out["reply"] = (f"I'll submit a {args.get('category') or 'Other'} reimbursement of {payroll.inr(float(amount))}. "
                            "You can attach the receipt from My requests afterwards.")
            out["action"] = {"tool": "reimbursement", "label": "Submit claim", "args": {
                "category": args.get("category") or "Other", "amount": float(amount), "description": args.get("description") or message}}
    elif tool == "request_document":
        doc = args.get("document_type") or "Employment certificate"
        out["reply"] = f"I'll request an {doc.lower()} from HR. It appears in My documents once HR approves."
        out["action"] = {"tool": "request_document", "label": f"Request {doc.lower()}", "args": {"document_type": doc}}
    elif tool == "attendance_correction":
        out["reply"] = (f"I'll ask HR to correct your attendance on {args.get('date')} to check-in {args.get('check_in', '09:30')}"
                        f"{' and check-out ' + args['check_out'] if args.get('check_out') else ''}. Confirm?")
        out["action"] = {"tool": "attendance_correction", "label": "Request correction", "args": {
            "date": args.get("date"), "check_in": args.get("check_in") or "09:30", "check_out": args.get("check_out") or "",
            "description": args.get("description") or message}}
    elif tool == "track_requests":
        rows = service_desk.list_for(employee_id=emp["id"])[:8]
        pending_leave = leave.list_requests(employee_id=emp["id"], status="pending")
        out["reply"] = "Here's what's open with HR:" if rows or pending_leave else "You have no HR requests."
        if rows:
            out["cards"].append({"type": "table", "columns": ["Ref", "Type", "Subject", "Status"],
                                 "rows": [[r["ref"], r["kind_label"], r["subject"], r["status"].replace("_", " ")] for r in rows]})
        if pending_leave:
            out["cards"].append({"type": "list", "items": [f"Leave {r['leave_name']} {_fmt_dates(r['start_date'], r['end_date'])} — waiting for {r['approver_name'] or 'HR'}" for r in pending_leave]})
    elif tool == "my_profile":
        out["reply"] = (f"You are {ctx['name']} ({ctx['employee_code']}), {ctx['designation']} in {ctx['department'] or 'no department yet'}. "
                        f"You joined on {ctx['date_of_joining']} ({ctx['tenure']}) and report to {ctx['manager']}. "
                        f"Status: {ctx['status']}{' until ' + ctx['probation_end'] if ctx['status'] == 'probation' and ctx['probation_end'] else ''}.")
    elif tool == "holidays":
        rows = db.fetch_all("SELECT * FROM holidays WHERE holiday_date >= ? ORDER BY holiday_date LIMIT 8", (date.today().isoformat(),))
        out["reply"] = "Upcoming company holidays:" if rows else "No upcoming holidays are published yet."
        if rows:
            out["cards"].append({"type": "table", "columns": ["Date", "Holiday"], "rows": [[r["holiday_date"], r["name"]] for r in rows]})
    elif tool == "attendance_summary":
        today = attendance.now_local().date()
        view = attendance.month_view(emp, today.year, today.month)
        s = view["summary"]
        out["reply"] = (f"This month so far: {s['present']} present, {s['late']} late, {s['half_day']} half day(s), "
                        f"{s['on_leave']} on leave, {s['absent']} absent.")
        out["suggestions"] = ["I forgot to check in yesterday", "What are the office hours?"]
    elif tool == "resign":
        notice = 15 if emp["status"] == "probation" else 60
        last_day = args.get("last_working_day") or (date.today() + timedelta(days=notice)).isoformat()
        out["reply"] = (f"I'm sorry to hear that. Your notice period is {notice} days, so your proposed last working day would be {last_day}. "
                        "If you confirm, I'll submit your resignation to HR. You can also talk to HR first.")
        out["action"] = {"tool": "resign", "label": "Submit resignation", "args": {"last_working_day": last_day, "description": args.get("description") or message}}
    else:
        out["reply"] = args.get("text") or ("Hi! I can check leave balances and apply leave, explain your payslip, answer policy questions, "
                                            "raise HR tickets and claims, request documents and correct attendance.")
        out["suggestions"] = ["Show my leave balance", "Explain my last payslip", "What is the reimbursement policy?"]
    return out


def execute(employee: dict, action: dict) -> dict:
    """Run a proposed action the employee confirmed. Services re-validate everything."""
    tool = (action or {}).get("tool")
    args = (action or {}).get("args") or {}
    if tool not in WRITE_TOOLS:
        raise ServiceError("Unknown action.")
    emp = people.get(employee["id"])
    if tool == "apply_leave":
        request = leave.apply(emp, leave_type_ref=args.get("leave_type") or "CL", start_date=args.get("start_date", ""),
                              end_date=args.get("end_date") or args.get("start_date", ""), half_day=bool(args.get("half_day")),
                              reason=str(args.get("reason") or ""))
        approver = request.get("approver_name") or "HR"
        return {"reply": f"Done — your {request['leave_name']} request for {_fmt_dates(request['start_date'], request['end_date'])} "
                         f"has been sent to {approver}. I'll notify you when it's decided."}
    kind_map = {"raise_ticket": "ticket", "reimbursement": "reimbursement", "request_document": "document",
                "attendance_correction": "attendance_correction", "resign": "exit"}
    payload = {}
    if tool == "request_document":
        payload = {"document_type": args.get("document_type")}
    elif tool == "attendance_correction":
        payload = {"date": args.get("date"), "check_in": args.get("check_in"), "check_out": args.get("check_out")}
    elif tool == "resign":
        payload = {"last_working_day": args.get("last_working_day")}
    request = service_desk.create(emp, kind=kind_map[tool], subject=str(args.get("subject") or ""), description=str(args.get("description") or ""),
                                  category=str(args.get("category") or args.get("document_type") or ""), amount=args.get("amount"), payload=payload)
    return {"reply": f"Done — {request['ref']} ({request['kind_label']}) has been sent to HR. Track it under My requests."}
