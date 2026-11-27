"""Company policies: HR publishes them; employees read them; the assistant answers from them.

``search`` is a small, dependency-free relevance ranker (term frequency with title boost)
that returns the best matching policy *passages*, so answers can quote the exact rule.
"""
from __future__ import annotations

import math
import re

from .. import db
from . import ServiceError

DEFAULT_POLICIES = [
    ("leave-policy", "Leave policy", "Time off",
     "Leave year: January to December. Quotas are pro-rated for employees who join during the year.\n"
     "Casual Leave (CL): 8 days a year. Apply at least 1 day in advance. Maximum 3 consecutive working days.\n"
     "Sick Leave (SL): 8 days a year. Can be applied on the same day or back-dated up to 7 days. A medical certificate may be requested for more than 2 consecutive days.\n"
     "Earned Leave (EL): 15 days a year, available after probation. Apply 7 days in advance. Unused EL carries forward.\n"
     "Work From Home (WFH): up to 24 days a year, maximum 5 consecutive days, with manager approval.\n"
     "Leave Without Pay (LWP): when other balances are exhausted; salary is reduced for those days.\n"
     "All leave is approved by the reporting manager, or by HR when no manager is assigned. Weekends and company holidays are not counted."),
    ("attendance-and-working-hours", "Attendance and working hours", "Time off",
     "Working days are Monday to Friday. Office hours are 09:30 to 18:30 with a one-hour break.\n"
     "Check in and check out on the employee portal every working day. A check-in after 09:45 is marked late.\n"
     "Working less than 4 hours in a day is recorded as a half day.\n"
     "If you forgot to check in or out, raise an attendance correction from the portal within 7 days."),
    ("payroll-and-payslips", "Payroll and payslips", "Pay",
     "Salaries are credited on the last working day of the month. Payslips are available on the employee portal.\n"
     "Salary structure: Basic is 40% of monthly CTC, HRA is 50% of Basic, Special Allowance is the balance after employer PF.\n"
     "Deductions: Employee Provident Fund at 12% of Basic (on Basic up to ₹15,000), Professional Tax of ₹200 when monthly gross exceeds ₹15,000, and Income Tax (TDS) based on your declarations.\n"
     "Loss of pay applies for unpaid leave. Raise a payroll ticket for any salary question."),
    ("reimbursement-policy", "Reimbursement policy", "Pay",
     "Business expenses are reimbursed against valid receipts submitted within 30 days of the expense.\n"
     "Eligible categories: travel for work, internet and phone (up to ₹1,000 a month), team meals approved by the manager, training and certification approved in advance.\n"
     "Submit a reimbursement request on the portal with the amount and a PDF or image of the receipt. Approved claims are paid with the next salary."),
    ("work-from-home-policy", "Work from home policy", "Workplace",
     "Employees may work from home with manager approval by applying for WFH leave on the portal.\n"
     "During WFH you must be reachable during office hours and attend scheduled meetings. Company data must only be accessed on company-approved devices."),
    ("code-of-conduct", "Code of conduct", "Workplace",
     "Treat colleagues, candidates and customers with respect. Harassment and discrimination of any kind are not tolerated.\n"
     "Protect confidential company and customer information. Report conflicts of interest to HR.\n"
     "Concerns can be raised confidentially with HR through an HR ticket."),
    ("probation-and-confirmation", "Probation and confirmation", "Employment",
     "New employees serve a 6-month probation. Performance check-ins happen at 3 and 6 months.\n"
     "Earned Leave becomes available after confirmation. The notice period during probation is 15 days."),
    ("exit-and-notice-period", "Exit and notice period", "Employment",
     "Confirmed employees serve a 60-day notice period; 15 days during probation.\n"
     "Submit your resignation on the portal with your proposed last working day. HR confirms the final date.\n"
     "Full and final settlement is processed within 45 days of the last working day, after asset handover. "
     "An experience letter can be requested from the portal after exit."),
]


def seed_defaults() -> None:
    if db.fetch_one("SELECT id FROM policies LIMIT 1"):
        return
    for slug, title, category, body in DEFAULT_POLICIES:
        stamp = db.now_iso()
        db.insert("policies", {"slug": slug, "title": title, "category": category, "body": body, "updated_by": "system",
                               "created_at": stamp, "updated_at": stamp})


def all_policies() -> list[dict]:
    return db.fetch_all("SELECT * FROM policies ORDER BY category, title")


def save(*, title: str, category: str, body: str, actor: str, policy_id: int | None = None) -> dict:
    title, body = (title or "").strip()[:150], (body or "").strip()[:20000]
    if len(title) < 3 or len(body) < 20:
        raise ServiceError("Give the policy a title and some content.")
    stamp = db.now_iso()
    if policy_id:
        if not db.update("policies", policy_id, {"title": title, "category": category or "General", "body": body,
                                                 "updated_by": actor, "updated_at": stamp}):
            raise ServiceError("Policy not found.", 404)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if db.fetch_one("SELECT id FROM policies WHERE slug = ?", (slug,)):
            slug = f"{slug}-{int(db.utcnow().timestamp())}"
        policy_id = db.insert("policies", {"slug": slug, "title": title, "category": category or "General", "body": body,
                                           "updated_by": actor, "created_at": stamp, "updated_at": stamp})
    db.audit(actor, "policy_saved", "policy", policy_id)
    return db.fetch_one("SELECT * FROM policies WHERE id = ?", (policy_id,))  # type: ignore[return-value]


def delete(policy_id: int, actor: str) -> None:
    db.execute("DELETE FROM policies WHERE id = ?", (policy_id,))
    db.audit(actor, "policy_deleted", "policy", policy_id)


_STOP = set("a an and are as at be by can do does for from how i if in is it me my of on or the to what when where which who why with you your".split())


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9₹]+", text.lower()) if t not in _STOP and len(t) > 1]


def search(query: str, limit: int = 3) -> list[dict]:
    q = _terms(query)
    if not q:
        return []
    passages = []
    for policy in all_policies():
        for line in [p.strip() for p in policy["body"].split("\n") if p.strip()]:
            passages.append((policy, line))
    if not passages:
        return []
    df: dict[str, int] = {}
    for _, line in passages:
        for term in set(_terms(line)):
            df[term] = df.get(term, 0) + 1
    # If the question names something the policies never mention (e.g. "maternity"), don't
    # guess from generic words like "leave" — the assistant will offer to ask HR instead.
    generic = {"policy", "policies", "rule", "rules", "company", "leave", "leaves", "days", "day", "year", "allowed", "many",
               "much", "there", "get", "take", "need", "want", "kairoz", "employee", "employees", "per", "any"}
    titles = " ".join(p["title"].lower() for p in all_policies())
    if any(len(term) > 3 and term not in generic and not df.get(term) and term not in titles for term in q):
        return []
    scored = []
    for policy, line in passages:
        terms = _terms(line)
        title_terms = set(_terms(policy["title"]))
        score, hits = 0.0, 0
        for term in q:
            tf = terms.count(term) + sum(1 for t in terms if len(term) > 3 and t.startswith(term[:4]) and t != term) * 0.5
            if tf:
                hits += 1
                score += (1 + math.log(tf)) * math.log(1 + len(passages) / (1 + df.get(term, 0)))
            if term in title_terms:
                score += 1.5
        # A passage must contain at least one query term itself (a title match alone is not an answer),
        # and multi-word questions need at least half their terms covered by passage + title.
        covered = hits + sum(1 for term in q if term in title_terms and term not in terms)
        if hits and covered >= max(1, len(q) // 2):
            scored.append((score, policy, line))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{"policy": p["title"], "slug": p["slug"], "passage": line, "score": round(s, 2)} for s, p, line in scored[:limit]]
