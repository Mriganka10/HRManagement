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


# ---------------------------------------------------------------------------- Arabic input
# Arabic requests are mapped onto the same English keywords the rule planner understands
# (dates, leave types, payslip, policy, tickets…). Names, amounts and times are kept. With an
# LLM configured the planner reads Arabic directly; this keeps the no-LLM path working too.

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_AR_PHRASES: list[tuple[str, str]] = [
    # days and dates
    (r"بعد غدا?|بعد بكر[هة]", " day after tomorrow "), (r"غدا|بكر[هة]", " tomorrow "), (r"اليوم", " today "),
    (r"امس|البارح[هة]", " yesterday "),
    (r"(?:يوم )?الاثنين", " monday "), (r"(?:يوم )?الثلاثاء", " tuesday "), (r"(?:يوم )?الاربعاء", " wednesday "),
    (r"(?:يوم )?الخميس", " thursday "), (r"(?:يوم )?الجمع[هة]", " friday "), (r"(?:يوم )?السبت", " saturday "),
    (r"(?:يوم )?الاحد", " sunday "), (r"القادم|المقبل|الجاي", " "),
    (r"يناير", " jan "), (r"فبراير", " feb "), (r"مارس", " mar "), (r"ابريل", " apr "), (r"مايو", " may "), (r"يونيو", " jun "),
    (r"يوليو", " jul "), (r"اغسطس", " aug "), (r"سبتمبر", " sep "), (r"اكتوبر", " oct "), (r"نوفمبر", " nov "), (r"ديسمبر", " dec "),
    (r"الشهر الماضي|الشهر السابق", " last month "),
    (r"لمد[هة] يومين|يومين", " for 2 days "), (r"لمد[هة] (\d+) (?:ايام|يوم)", r" for \1 days "), (r"(\d+) (?:ايام|يوم)", r" for \1 days "),
    (r"نصف يوم", " half day "),
    # leave
    (r"(?:اجاز[هة] )?مرضي[هة]|مريض|مرض", " sick leave "), (r"اجاز[هة] (?:عارض[هة]|طارئ[هة])", " casual leave "),
    (r"اجاز[هة] (?:سنوي[هة]|مكتسب[هة]|اعتيادي[هة])", " earned leave "), (r"العمل من المنزل|عمل من المنزل|عن بعد", " work from home "),
    (r"بدون راتب|غير مدفوع[هة]", " leave without pay "),
    (r"رصيد", " balance "), (r"اجازاتي|اجازات|اجاز[هة]|عطل[هة] شخصي[هة]", " leave "),
    (r"المتبقي[هة]?|متبقي[هة]?|باقي", " left "), (r"كم", " how many "),
    # pay
    (r"(?:قسيم[هة]|كشف|مسير|ايصال) (?:ال)?راتب", " payslip "), (r"راتبي", " my salary "), (r"(?:ال)?راتب", " salary "),
    (r"(?:ال)?خصومات|خصم", " deduction "), (r"صافي", " net pay "), (r"الضريب[هة]", " tds "),
    # requests and documents
    (r"نسيت (?:تسجيل )?(?:الحضور|الدخول|البصم[هة]|التوقيع)", " forgot to check in "), (r"تصحيح (?:ال)?حضور", " attendance correction "),
    (r"شهاد[هة] (?:عمل|توظيف)", " employment certificate "), (r"شهاد[هة] راتب", " salary certificate "),
    (r"(?:شهاد[هة]|خطاب) خبر[هة]", " experience letter "), (r"اثبات (?:ال)?عنوان", " address proof letter "), (r"شهاد[هة]", " certificate "),
    (r"استرداد|تعويض|مطالب[هة]", " reimburse "), (r"(?:ال)?سفر|(?:ال)?مواصلات|(?:ال)?تنقل", " travel "),
    (r"روبي[هة]|روبيات", " rupees "),
    (r"حال[هة]|وضع", " status of "), (r"طلباتي", " my requests "), (r"تذاكري", " my tickets "),
    (r"(?:افتح|ارفع|قدم) (?:لي )?تذكر[هة]|تذكر[هة]", " raise a ticket "), (r"شكوى", " complaint "),
    (r"لابتوب|حاسوبي|الحاسوب|الكمبيوتر", " laptop "), (r"لا يعمل|معطل", " not working "), (r"مشكل[هة]", " issue "),
    (r"تامين", " insurance "),
    (r"استقيل|استقالتي|استقال[هة]|ترك العمل", " resign "),
    # attendance, holidays, profile
    (r"(?:ال)?عطل(?: الرسمي[هة])?|(?:ال)?اجازات الرسمي[هة]", " holiday "), (r"(?:ال)?حضور|(?:ال)?دوام", " attendance "),
    (r"متاخر|تاخير", " late "), (r"صباحا|ص\b", " am "), (r"مساء|م\b", " pm "), (r"الساع[هة]", " "),
    (r"(?:من هو )?مديري", " who is my manager "), (r"قسمي", " my department "), (r"(?:مسماي الوظيفي|وظيفتي)", " my designation "),
    (r"تاريخ انضمامي|تاريخ التحاقي", " my joining "), (r"فتر[هة] (?:التجرب[هة]|الاختبار)", " my probation "),
    (r"رقمي الوظيفي|الرقم الوظيفي", " employee id "),
    # policies and question words
    (r"(?:فتر[هة]|مهل[هة]) (?:ال)?اشعار", " notice period "), (r"ساعات (?:العمل|الدوام)", " office hours "),
    (r"(?:قواعد|سياس[هة]) (?:اللباس|الزي)", " dress code "), (r"سياس[هة]|سياسات", " policy "), (r"قواعد|قانون|لوائح", " rules "),
    (r"ما هي|ما هو|ماهي|ماهو|ما", " what is "), (r"كيف", " how "), (r"هل", " can "),
    (r"اريد|احتاج|ابغى|ابي", " i want "), (r"اطلب|طلب", " apply "),
    (r"مرحبا|السلام عليكم|اهلا", " hello "),
]


def has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def from_arabic(text: str) -> str:
    """Rewrite an Arabic request as the English keywords the rule planner understands."""
    t = (text or "").translate(_AR_DIGITS)
    t = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", t)          # diacritics, tatweel
    t = re.sub(r"[أإآ]", "ا", t).replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("،", ",").replace("؟", "?")
    t = re.sub(r"\bو(?=[\u0600-\u06FF])", " ", t)                     # leading "and"
    for pattern, english in _AR_PHRASES:
        t = re.sub(pattern, english, t)
    t = re.sub(r"[\u0600-\u06FF]+", " ", t)                          # words we do not map
    return re.sub(r"\s+", " ", t).strip()


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
    t = (from_arabic(text) if has_arabic(text) else text).lower()
    start, end = parse_dates(t)
    half = bool(re.search(r"half[\s-]?day", t))
    if re.search(r"resign|quit (my|the) job|put (in|down) my papers|leaving the company", t) and not re.search(r"policy|how|what", t):
        return {"tool": "resign", "args": {"last_working_day": start.isoformat() if start else None, "description": text}}
    if re.search(r"\bpolic(y|ies)\b|\brules?\b|\bentitle", t) or (re.search(r"^(what|how|can|is|are|do|does|when|why)\b", t) and not re.search(
            r"my (leave|balance|payslip|salary|request|manager|attendance|probation|profile|designation|department|joining)|i (need|want|forgot)|apply|raise|reimburse .*\d", t)
            and not start and _amount(t) is None and not re.search(r"payslip|deduction|\bpf\b|\btds\b|holiday|leave|manager|net pay|salary", t)):
        return {"tool": "policy", "args": {"query": t if has_arabic(text) else text}}
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
        return {"tool": "answer", "args": {"text": "", "ask": "which_dates_long"}}
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
    return {"tool": "policy", "args": {"query": t if has_arabic(text) else text}}


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
answer(text) — only for greetings or when you must ask a clarifying question (e.g. dates missing).
The message may be in Arabic or English. Always write args.query, category, subject and document_type in English
(policies are searched in English); write answer.text in the employee's language."""


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


# ---------------------------------------------------------------------------- replies (English / Arabic)

_REPLIES: dict[str, tuple[str, str]] = {
    "balance": ("Here is your leave balance for this year:", "هذا رصيد إجازاتك لهذا العام:"),
    "which_dates": ("Which dates do you need? For example “sick leave today” or “casual leave on 12 Dec”.",
                    "ما التواريخ التي تحتاجها؟ مثلًا: «إجازة مرضية اليوم» أو «إجازة عارضة يوم 12 ديسمبر»."),
    "which_dates_long": ("Sure — which dates? For example: “casual leave on 12 Dec”, “sick leave today”, or “WFH from next Monday for 2 days”.",
                         "بالتأكيد — ما التواريخ؟ مثلًا: «إجازة عارضة يوم 12 ديسمبر» أو «إجازة مرضية اليوم» أو «العمل من المنزل يوم الاثنين القادم لمدة يومين»."),
    "eligible": ("You're eligible for {name} on {dates} ({days} working day(s)). You'll have {left} day(s) left. It will go to {approver} for approval. Shall I apply?",
                 "أنت مؤهل لـ{name} في {dates} ({days} يوم عمل). سيتبقى لك {left} يوم. سيُرسل الطلب إلى {approver} للموافقة. هل أقدّم الطلب؟"),
    "not_eligible": ("I can't apply {name} for {dates} yet:", "لا يمكنني تقديم {name} في {dates} حاليًا:"),
    "my_leave": ("Your recent leave requests:", "طلبات إجازتك الأخيرة:"),
    "no_leave": ("You have no leave requests yet.", "ليست لديك طلبات إجازة حتى الآن."),
    "no_payslip": ("No payslip has been generated for you yet. Payslips appear here after HR runs payroll for the month.",
                   "لم تُصدر لك قسيمة راتب بعد. تظهر القسائم هنا بعد أن تشغّل الموارد البشرية مسير رواتب الشهر."),
    "payslip": ("Your payslip for {period}: net pay {net}.", "قسيمة راتبك لشهر {period}: صافي الراتب {net}."),
    "policy_missing": ("I couldn't find that in the company policies. I can raise an HR ticket so someone from HR answers you.",
                       "لم أجد ذلك في سياسات الشركة. يمكنني فتح تذكرة لدى الموارد البشرية ليجيبك أحد أعضاء الفريق."),
    "policy_hit": ("From the {policy}: {passage}", "من {policy}: {passage}"),
    "ticket": ("I'll raise this as an HR ticket. Check the details and confirm.", "سأفتح تذكرة لدى الموارد البشرية بهذا الطلب. راجع التفاصيل ثم أكّد."),
    "claim_amount": ("How much is the claim? For example “reimburse ₹1,200 for travel to the client office”.",
                     "ما قيمة المطالبة؟ مثلًا: «استرداد ₹1,200 لتكاليف السفر إلى مكتب العميل»."),
    "claim": ("I'll submit a {category} reimbursement of {amount}. You can attach the receipt from My requests afterwards.",
              "سأقدّم مطالبة استرداد ({category}) بمبلغ {amount}. يمكنك إرفاق الإيصال لاحقًا من «طلباتي»."),
    "document": ("I'll request an {doc} from HR. It appears in My documents once HR approves.",
                 "سأطلب {doc} من الموارد البشرية. سيظهر في «مستنداتي» بعد موافقة الموارد البشرية."),
    "correction": ("I'll ask HR to correct your attendance on {date} to check-in {check_in}{check_out}. Confirm?",
                   "سأطلب من الموارد البشرية تصحيح حضورك يوم {date} ليكون الحضور {check_in}{check_out}. هل تؤكد؟"),
    "correction_out": (" and check-out {time}", " والانصراف {time}"),
    "requests": ("Here's what's open with HR:", "هذه طلباتك المفتوحة لدى الموارد البشرية:"),
    "no_requests": ("You have no HR requests.", "ليست لديك طلبات لدى الموارد البشرية."),
    "pending_leave": ("Leave {name} {dates} — waiting for {approver}", "إجازة {name} {dates} — بانتظار {approver}"),
    "profile": ("You are {name} ({code}), {designation} in {department}. You joined on {joined} ({tenure}) and report to {manager}. Status: {status}{until}.",
                "أنت {name} ({code})، {designation} في {department}. انضممت في {joined} ({tenure}) وترفع تقاريرك إلى {manager}. الحالة: {status}{until}."),
    "until": (" until {date}", " حتى {date}"),
    "no_department": ("no department yet", "لم يُحدَّد قسم بعد"),
    "holidays": ("Upcoming company holidays:", "العطل الرسمية القادمة للشركة:"),
    "no_holidays": ("No upcoming holidays are published yet.", "لم تُنشر أي عطل قادمة بعد."),
    "attendance": ("This month so far: {present} present, {late} late, {half} half day(s), {leave} on leave, {absent} absent.",
                   "هذا الشهر حتى الآن: {present} حضور، {late} تأخير، {half} نصف يوم، {leave} إجازة، {absent} غياب."),
    "resign": ("I'm sorry to hear that. Your notice period is {notice} days, so your proposed last working day would be {last}. "
               "If you confirm, I'll submit your resignation to HR. You can also talk to HR first.",
               "يؤسفني سماع ذلك. فترة إشعارك {notice} يومًا، لذا سيكون آخر يوم عمل مقترح هو {last}. "
               "إذا أكّدت، سأرسل استقالتك إلى الموارد البشرية. يمكنك أيضًا التحدث مع الموارد البشرية أولًا."),
    "intro": ("Hi! I can check leave balances and apply leave, explain your payslip, answer policy questions, "
              "raise HR tickets and claims, request documents and correct attendance.",
              "مرحبًا! يمكنني الاطلاع على رصيد إجازاتك وتقديم الإجازات، وشرح قسيمة راتبك، والإجابة عن أسئلة السياسات، "
              "وفتح تذاكر ومطالبات لدى الموارد البشرية، وطلب المستندات وتصحيح الحضور."),
    "done_leave": ("Done — your {name} request for {dates} has been sent to {approver}. I'll notify you when it's decided.",
                   "تم — أُرسل طلب {name} في {dates} إلى {approver}. سأبلغك عند البت فيه."),
    "btn_apply": ("Apply {name}", "تقديم {name}"), "btn_ask_hr": ("Ask HR", "اسأل الموارد البشرية"),
    "btn_ticket": ("Raise ticket", "فتح تذكرة"), "btn_claim": ("Submit claim", "تقديم المطالبة"),
    "btn_document": ("Request {doc}", "طلب {doc}"), "btn_correction": ("Request correction", "طلب التصحيح"),
    "btn_resign": ("Submit resignation", "تقديم الاستقالة"),
    "done_request": ("Done — {ref} ({kind}) has been sent to HR. Track it under My requests.",
                     "تم — أُرسل {ref} ({kind}) إلى الموارد البشرية. تابعه من «طلباتي»."),
}
_AR_NAMES = {
    "Casual Leave": "إجازة عارضة", "Sick Leave": "إجازة مرضية", "Earned Leave": "إجازة مكتسبة", "Work From Home": "العمل من المنزل",
    "Leave Without Pay": "إجازة بدون راتب", "Leave": "الإجازة", "HR": "الموارد البشرية", "HR (no reporting manager assigned)": "الموارد البشرية (لم يُعيَّن مدير مباشر)",
    "Travel": "السفر", "Internet & phone": "الإنترنت والهاتف", "Meals": "الوجبات", "Training & certification": "التدريب والشهادات",
    "Medical": "طبي", "Other": "أخرى", "Employment certificate": "شهادة عمل", "Salary certificate": "شهادة راتب",
    "Address proof letter": "خطاب إثبات عنوان", "Experience letter": "شهادة خبرة",
    "active": "نشط", "probation": "فترة تجربة", "notice": "فترة إشعار", "exited": "غادر",
    "pending": "قيد الانتظار", "approved": "موافق عليه", "rejected": "مرفوض", "cancelled": "ملغى", "open": "مفتوح",
    "in progress": "قيد التنفيذ", "resolved": "تم الحل", "HR ticket": "تذكرة موارد بشرية", "Reimbursement": "استرداد نفقات",
    "Document request": "طلب مستند", "Attendance correction": "تصحيح حضور", "Resignation / exit": "استقالة / مغادرة",
}


def _say(lang: str, key: str, **values: object) -> str:
    english, arabic = _REPLIES[key]
    return (arabic if lang == "ar" else english).format(**values)


def _name(lang: str, value: str | None) -> str:
    value = value or ""
    return _AR_NAMES.get(value, value) if lang == "ar" else value


def _tenure(lang: str, ctx: dict) -> str:
    if lang != "ar":
        return ctx["tenure"]
    years, _, rest = ctx["tenure"].partition(" years ")
    return f"{years} سنة و{rest.split(' ')[0]} شهر"


# ---------------------------------------------------------------------------- acting

def _fmt_dates(start: str, end: str, lang: str = "en") -> str:
    return start if start == end else f"{start} {'إلى' if lang == 'ar' else 'to'} {end}"


def _greeting(message: str) -> bool:
    text = (from_arabic(message) if has_arabic(message) else message).lower().strip(" !.?,")
    return bool(re.fullmatch(r"(hi|hello|hey|hii+|good (morning|afternoon|evening)|thanks?( you)?|thank you)( there)?", text))


def respond(employee: dict, message: str, history: list[dict] | None = None, lang: str = "en") -> dict:
    """Plan → act for one message. ``lang`` is the interface language; replies use it."""
    message = (message or "").strip()[:1000]
    if not message:
        raise ServiceError("Type a question.")
    emp = people.get(employee["id"])
    ctx = context(emp)
    lang = "ar" if lang == "ar" else "en"
    step = {"tool": "answer", "args": {}, "planner": "rules"} if _greeting(message) else plan(message, ctx, history or [])
    tool, args = step["tool"], step.get("args") or {}
    out: dict[str, Any] = {"tool": tool, "planner": step["planner"], "reply": "", "cards": [], "action": None, "suggestions": []}

    if tool == "leave_balance":
        rows = leave.balances(emp)
        out["reply"] = _say(lang, "balance")
        out["cards"].append({"type": "table", "columns": ["Leave", "Available", "Used", "Pending"],
                             "rows": [[_name(lang, b["name"]), f"{b['available']:g}", f"{b['used']:g}", f"{b['pending']:g}"] for b in rows]})
        out["suggestions"] = ["Apply casual leave tomorrow", "What is the leave policy?"]
    elif tool in {"check_leave", "apply_leave"}:
        start = args.get("start_date")
        if not start:
            out["reply"] = _say(lang, "which_dates")
        else:
            end = args.get("end_date") or start
            check = leave.check_eligibility(emp, args.get("leave_type") or "CL", start, end, half_day=bool(args.get("half_day")))
            name = _name(lang, (check.get("leave_type") or {}).get("name", "Leave"))
            if check["eligible"]:
                approver = _name(lang, ctx["manager"])
                out["reply"] = _say(lang, "eligible", name=name, dates=_fmt_dates(check["start_date"], check["end_date"], lang),
                                    days=f"{check['days']:g}", left=f"{check['balance']['available'] - check['days']:g}", approver=approver)
                out["action"] = {"tool": "apply_leave", "label": _say(lang, "btn_apply", name=name), "args": {
                    "leave_type": check["leave_type"]["code"], "start_date": check["start_date"], "end_date": check["end_date"],
                    "half_day": check["half_day"], "reason": args.get("description") or message}}
            else:
                out["reply"] = _say(lang, "not_eligible", name=name, dates=_fmt_dates(check.get("start_date", start), check.get("end_date", end), lang))
                out["cards"].append({"type": "list", "items": check["problems"]})
                out["suggestions"] = ["Show my leave balance", "What is the leave policy?"]
    elif tool == "my_leave":
        rows = leave.list_requests(employee_id=emp["id"], limit=8)
        out["reply"] = _say(lang, "my_leave" if rows else "no_leave")
        if rows:
            out["cards"].append({"type": "table", "columns": ["Leave", "Dates", "Days", "Status"],
                                 "rows": [[_name(lang, r["leave_name"]), _fmt_dates(r["start_date"], r["end_date"], lang), f"{r['days']:g}", r["status"]] for r in rows]})
    elif tool == "payslip":
        period = args.get("period")
        slip = (db.fetch_one("SELECT * FROM payslips WHERE employee_id = ? AND period = ?", (emp["id"], period)) if period else None) or \
            db.fetch_one("SELECT * FROM payslips WHERE employee_id = ? ORDER BY period DESC LIMIT 1", (emp["id"],))
        if not slip:
            out["reply"] = _say(lang, "no_payslip")
        else:
            out["reply"] = _say(lang, "payslip", period=slip["period"], net=payroll.inr(slip["net_pay"]))
            out["cards"].append({"type": "list", "items": payroll.explain(slip)})
            out["cards"].append({"type": "link", "label": "Open payslip", "href": f"/api/me/payslips/{slip['id']}/view"})
    elif tool == "policy":
        hits = policies.search(args.get("query") or message)
        if not hits or hits[0]["score"] < 1.0:
            out["reply"] = _say(lang, "policy_missing")
            out["action"] = {"tool": "raise_ticket", "label": _say(lang, "btn_ask_hr"), "args": {"category": "Policy question", "subject": message[:90], "description": message}}
        else:
            out["reply"] = _say(lang, "policy_hit", policy=hits[0]["policy"], passage=hits[0]["passage"])
            if len(hits) > 1:
                out["cards"].append({"type": "list", "items": [f"{h['policy']}: {h['passage']}" for h in hits[1:]]})
    elif tool == "raise_ticket":
        out["reply"] = _say(lang, "ticket")
        out["action"] = {"tool": "raise_ticket", "label": _say(lang, "btn_ticket"), "args": {
            "category": args.get("category") or "Other", "subject": args.get("subject") or message[:90], "description": args.get("description") or message}}
    elif tool == "reimbursement":
        amount = args.get("amount")
        if not amount:
            out["reply"] = _say(lang, "claim_amount")
        else:
            out["reply"] = _say(lang, "claim", category=_name(lang, args.get("category") or "Other"), amount=payroll.inr(float(amount)))
            out["action"] = {"tool": "reimbursement", "label": _say(lang, "btn_claim"), "args": {
                "category": args.get("category") or "Other", "amount": float(amount), "description": args.get("description") or message}}
    elif tool == "request_document":
        doc = args.get("document_type") or "Employment certificate"
        out["reply"] = _say(lang, "document", doc=_name(lang, doc) if lang == "ar" else doc.lower())
        out["action"] = {"tool": "request_document", "label": _say(lang, "btn_document", doc=_name(lang, doc) if lang == "ar" else doc.lower()), "args": {"document_type": doc}}
    elif tool == "attendance_correction":
        out["reply"] = _say(lang, "correction", date=args.get("date"), check_in=args.get("check_in", "09:30"),
                            check_out=_say(lang, "correction_out", time=args["check_out"]) if args.get("check_out") else "")
        out["action"] = {"tool": "attendance_correction", "label": _say(lang, "btn_correction"), "args": {
            "date": args.get("date"), "check_in": args.get("check_in") or "09:30", "check_out": args.get("check_out") or "",
            "description": args.get("description") or message}}
    elif tool == "track_requests":
        rows = service_desk.list_for(employee_id=emp["id"])[:8]
        pending_leave = leave.list_requests(employee_id=emp["id"], status="pending")
        out["reply"] = _say(lang, "requests" if rows or pending_leave else "no_requests")
        if rows:
            out["cards"].append({"type": "table", "columns": ["Ref", "Type", "Subject", "Status"],
                                 "rows": [[r["ref"], _name(lang, r["kind_label"]), r["subject"], _name(lang, r["status"].replace("_", " "))] for r in rows]})
        if pending_leave:
            out["cards"].append({"type": "list", "items": [_say(lang, "pending_leave", name=_name(lang, r["leave_name"]), dates=_fmt_dates(r["start_date"], r["end_date"], lang),
                                                                approver=r["approver_name"] or _name(lang, "HR")) for r in pending_leave]})
    elif tool == "my_profile":
        until = _say(lang, "until", date=ctx["probation_end"]) if ctx["status"] == "probation" and ctx["probation_end"] else ""
        out["reply"] = _say(lang, "profile", name=ctx["name"], code=ctx["employee_code"], designation=ctx["designation"],
                            department=ctx["department"] or _say(lang, "no_department"), joined=ctx["date_of_joining"],
                            tenure=_tenure(lang, ctx), manager=_name(lang, ctx["manager"]), status=_name(lang, ctx["status"]), until=until)
    elif tool == "holidays":
        rows = db.fetch_all("SELECT * FROM holidays WHERE holiday_date >= ? ORDER BY holiday_date LIMIT 8", (date.today().isoformat(),))
        out["reply"] = _say(lang, "holidays" if rows else "no_holidays")
        if rows:
            out["cards"].append({"type": "table", "columns": ["Date", "Holiday"], "rows": [[r["holiday_date"], r["name"]] for r in rows]})
    elif tool == "attendance_summary":
        today = attendance.now_local().date()
        view = attendance.month_view(emp, today.year, today.month)
        s = view["summary"]
        out["reply"] = _say(lang, "attendance", present=s["present"], late=s["late"], half=s["half_day"], leave=s["on_leave"], absent=s["absent"])
        out["suggestions"] = ["I forgot to check in yesterday", "What are the office hours?"]
    elif tool == "resign":
        notice = 15 if emp["status"] == "probation" else 60
        last_day = args.get("last_working_day") or (date.today() + timedelta(days=notice)).isoformat()
        out["reply"] = _say(lang, "resign", notice=notice, last=last_day)
        out["action"] = {"tool": "resign", "label": _say(lang, "btn_resign"), "args": {"last_working_day": last_day, "description": args.get("description") or message}}
    else:
        out["reply"] = (_say(lang, args["ask"]) if args.get("ask") else "") or args.get("text") or _say(lang, "intro")
        out["suggestions"] = ["Show my leave balance", "Explain my last payslip", "What is the reimbursement policy?"]
    return out


def execute(employee: dict, action: dict, lang: str = "en") -> dict:
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
        approver = request.get("approver_name") or _name(lang, "HR")
        return {"reply": _say(lang, "done_leave", name=_name(lang, request["leave_name"]),
                              dates=_fmt_dates(request["start_date"], request["end_date"], lang), approver=approver)}
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
    return {"reply": _say(lang, "done_request", ref=request["ref"], kind=_name(lang, request["kind_label"]))}
