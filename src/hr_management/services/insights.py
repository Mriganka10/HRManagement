"""HR dashboard numbers: workforce, hiring funnel, today's attendance, pending work,
upcoming events and attrition. One call, cheap queries."""
from __future__ import annotations

from datetime import date, timedelta

from .. import db, pipeline
from . import attendance, people, performance

FUNNEL = [
    ("Applied", None),
    ("Shortlisted (ATS)", {pipeline.TEST_PENDING, pipeline.TEST_IN_PROGRESS, pipeline.TEST_REJECTED, pipeline.INTERVIEW_PENDING,
                           pipeline.INTERVIEW_IN_PROGRESS, pipeline.INTERVIEW_REJECTED, pipeline.INTERVIEW_PASSED,
                           pipeline.SELECTED, pipeline.NOT_SELECTED, pipeline.HIRED}),
    ("Passed mock test", {pipeline.INTERVIEW_PENDING, pipeline.INTERVIEW_IN_PROGRESS, pipeline.INTERVIEW_REJECTED,
                          pipeline.INTERVIEW_PASSED, pipeline.SELECTED, pipeline.NOT_SELECTED, pipeline.HIRED}),
    ("Cleared interview", {pipeline.INTERVIEW_PASSED, pipeline.SELECTED, pipeline.NOT_SELECTED, pipeline.HIRED}),
    ("Selected", {pipeline.SELECTED, pipeline.HIRED}),
    ("Hired", {pipeline.HIRED}),
]


def dashboard() -> dict:
    today = date.today()
    employees = db.fetch_all("SELECT id, status, department, date_of_joining, exit_date FROM employees")
    active = [e for e in employees if e["status"] != "exited"]
    by_department: dict[str, int] = {}
    for e in active:
        by_department[e["department"] or "Unassigned"] = by_department.get(e["department"] or "Unassigned", 0) + 1
    year_ago = (today - timedelta(days=365)).isoformat()
    exits = [e for e in employees if e["status"] == "exited" and (e["exit_date"] or "") >= year_ago]
    joined_year = [e for e in employees if e["date_of_joining"] >= year_ago]
    avg_headcount = max(1, (len(active) + len(active) - len(joined_year) + len(exits)) / 2)
    stages = db.stage_counts()
    total_apps = sum(stages.values())
    funnel = [{"label": label, "count": total_apps if keys is None else sum(stages.get(k, 0) for k in keys)} for label, keys in FUNNEL]
    openings = db.fetch_all("SELECT key, title, department, openings FROM job_openings WHERE status = 'open'")
    hired_by_role = {r["role_key"]: int(r["n"]) for r in db.fetch_all(
        "SELECT role_key, COUNT(*) AS n FROM applications WHERE stage = 'hired' GROUP BY role_key")}
    return {
        "headcount": {"total": len(active), "probation": sum(1 for e in active if e["status"] == "probation"),
                      "notice": sum(1 for e in active if e["status"] == "notice"),
                      "joined_30d": sum(1 for e in active if e["date_of_joining"] >= (today - timedelta(days=30)).isoformat()),
                      "by_department": [{"department": k, "count": v} for k, v in sorted(by_department.items(), key=lambda x: -x[1])]},
        "attrition_12m": round(100 * len(exits) / avg_headcount, 1),
        "funnel": funnel,
        "stages": stages,
        "open_roles": [{**r, "hired": hired_by_role.get(r["key"], 0),
                        "applicants": int((db.fetch_one("SELECT COUNT(*) AS n FROM applications WHERE role_key = ?", (r["key"],)) or {}).get("n", 0))}
                       for r in openings],
        "attendance_today": attendance.day_overview()["counts"],
        "pending": {
            "leave": int((db.fetch_one("SELECT COUNT(*) AS n FROM leave_requests WHERE status = 'pending'") or {}).get("n", 0)),
            "leave_hr": int((db.fetch_one("SELECT COUNT(*) AS n FROM leave_requests WHERE status = 'pending' AND approver_employee_id IS NULL") or {}).get("n", 0)),
            "requests": int((db.fetch_one("SELECT COUNT(*) AS n FROM service_requests WHERE status IN ('open', 'in_progress')") or {}).get("n", 0)),
            "onboarding": int((db.fetch_one("SELECT COUNT(*) AS n FROM onboarding WHERE status = 'pending'") or {}).get("n", 0)),
            "awaiting_decision": stages.get(pipeline.INTERVIEW_PASSED, 0),
            "reviews_due": len(performance.due_reviews()),
        },
        "on_leave_today": db.fetch_all(
            """SELECT e.full_name, e.department, lt.name AS leave_name, lr.end_date FROM leave_requests lr
               JOIN employees e ON e.id = lr.employee_id JOIN leave_types lt ON lt.id = lr.leave_type_id
               WHERE lr.status = 'approved' AND lr.start_date <= ? AND lr.end_date >= ?""", (today.isoformat(), today.isoformat())),
        "events": people.upcoming_events(30),
        "recent_hires": db.fetch_all("SELECT id, employee_code, full_name, designation, date_of_joining FROM employees ORDER BY id DESC LIMIT 5"),
    }
