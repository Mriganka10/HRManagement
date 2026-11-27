"""Reference data on every start, and optional demo data for local trials.

``seed_reference_data`` (idempotent, runs at startup): job openings from catalog/roles.json,
leave types + national holidays, default company policies, first HR admin (if configured).

``seed_demo`` (``python -m hr_management seed-demo``; refuses to run in production): an HR admin,
a small org chart with managers, salary structures, this month's attendance, a few leave
requests, service requests, performance reviews and payslips — so every screen has data.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from .. import db, roles
from ..settings import company_tz, get_settings
from . import accounts, leave, payroll, policies


def seed_reference_data() -> None:
    roles.seed_from_catalog()
    leave.seed_defaults()
    policies.seed_defaults()
    accounts.bootstrap_hr_admin()


DEMO_PEOPLE = [
    # name, email, designation, department, role_key, ctc, years ago joined, manager index, skills
    ("Ananya Sen", "ananya.sen@kairoz.demo", "Engineering Manager", "Engineering", "backend-developer", 3200000, 4.2, None,
     ["Python", "AWS", "System Design", "Kubernetes", "Leadership", "SQL"]),
    ("Rohit Mehra", "rohit.mehra@kairoz.demo", "Senior Backend Developer", "Engineering", "backend-developer", 2000000, 2.5, 0,
     ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Redis", "SQL", "REST APIs"]),
    ("Priya Nair", "priya.nair@kairoz.demo", "Frontend Developer", "Engineering", "frontend-developer", 1100000, 1.3, 0,
     ["JavaScript", "TypeScript", "React", "CSS", "HTML", "Jest", "Git"]),
    ("Arjun Das", "arjun.das@kairoz.demo", "Machine Learning Engineer", "AI", "ml-engineer", 1600000, 1.8, 0,
     ["Python", "PyTorch", "Machine Learning", "Deep Learning", "NLP", "SQL", "Docker", "MLOps"]),
    ("Sneha Roy", "sneha.roy@kairoz.demo", "Data Analyst", "Analytics", "data-analyst", 750000, 0.8, 3,
     ["SQL", "Excel", "Python", "Pandas", "Power BI", "Statistics"]),
    ("Vikram Iyer", "vikram.iyer@kairoz.demo", "DevOps Engineer", "Platform", "devops-engineer", 1400000, 0.3, 0,
     ["AWS", "Terraform", "Docker", "Kubernetes", "Linux", "CI/CD", "Bash"]),
]


def seed_demo() -> dict:
    cfg = get_settings()
    if cfg.is_production:
        raise RuntimeError("Refusing to load demo data in production.")
    seed_reference_data()
    created: dict = {"hr": None, "employees": []}
    hr = db.fetch_one("SELECT * FROM accounts WHERE email = ?", ("hr.admin@kairoz.demo",))
    if not hr:
        hr, _ = accounts.create_account(email="hr.admin@kairoz.demo", full_name="Meera Kapoor", role="hr_admin", password="KairozHR2026")
        db.update("accounts", hr["id"], {"must_change_password": 0})
    created["hr"] = {"user_id": hr["user_id"], "password": "KairozHR2026"}
    rng = random.Random(7)
    today = date.today()
    ids: list[int] = []
    for name, email, designation, department, role_key, ctc, years, manager_index, skills in DEMO_PEOPLE:
        existing = db.fetch_one("SELECT * FROM employees WHERE email = ?", (email,))
        if existing:
            ids.append(existing["id"])
            continue
        joined = (today - timedelta(days=int(365 * years))).isoformat()
        probation_end = (date.fromisoformat(joined) + timedelta(days=180)).isoformat()
        code = accounts.next_user_id("employee")
        stamp = db.now_iso()
        employee_id = db.insert("employees", {
            "employee_code": code, "full_name": name, "email": email, "phone": f"+91 98{rng.randint(10000000, 99999999)}",
            "designation": designation, "department": department, "role_key": role_key,
            "manager_id": ids[manager_index] if manager_index is not None else None, "date_of_joining": joined,
            "work_location": "Kolkata", "status": "probation" if probation_end > today.isoformat() else "active",
            "probation_end": probation_end, "date_of_birth": f"{rng.randint(1988, 2000)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "address": "Salt Lake, Kolkata, West Bengal", "pan_number": f"ABCDE{rng.randint(1000, 9999)}F",
            "bank_account_name": name, "bank_account_number": str(rng.randint(10**11, 10**12 - 1)), "bank_ifsc": "HDFC0001234",
            "skills": skills, "annual_ctc": ctc, "created_at": stamp, "updated_at": stamp,
        })
        account, _ = accounts.create_account(email=email, full_name=name, role="employee", employee_id=employee_id,
                                             user_id=code, password="Welcome2026")
        db.update("accounts", account["id"], {"must_change_password": 0})
        db.update("employees", employee_id, {"account_id": account["id"]})
        payroll.save_structure(employee_id, ctc, monthly_tds=round(ctc / 12 * 0.06, -2), effective_from=joined, actor="demo")
        ids.append(employee_id)
        created["employees"].append({"name": name, "user_id": code, "password": "Welcome2026"})
    _demo_activity(ids, rng)
    return created


def _demo_activity(ids: list[int], rng: random.Random) -> None:
    tz = company_tz()
    today = date.today()
    if db.fetch_one("SELECT id FROM attendance WHERE source = 'demo' LIMIT 1"):
        return
    for employee_id in ids:
        employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
        current = today.replace(day=1)
        while current < today:
            if current.weekday() < 5 and current.isoformat() >= employee["date_of_joining"] and rng.random() > 0.08:
                start = datetime(current.year, current.month, current.day, 9, rng.randint(5, 55), tzinfo=tz)
                end = start + timedelta(hours=8 + rng.random() * 1.5)
                db.insert("attendance", {"employee_id": employee_id, "work_date": current.isoformat(),
                                         "check_in": start.isoformat(timespec="seconds"), "check_out": end.isoformat(timespec="seconds"),
                                         "status": "late" if start.minute > 45 else "present", "source": "demo"})
            current += timedelta(days=1)
    cl = db.fetch_one("SELECT id FROM leave_types WHERE code = 'CL'")
    sl = db.fetch_one("SELECT id FROM leave_types WHERE code = 'SL'")
    next_week = today + timedelta(days=(7 - today.weekday()) % 7 + 7)
    for employee_id, type_id, start, days, status in ((ids[1], cl["id"], next_week, 2, "pending"), (ids[2], sl["id"], today - timedelta(days=12), 1, "approved"),
                                                      (ids[4], cl["id"], next_week + timedelta(days=2), 1, "pending")):
        employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
        db.insert("leave_requests", {"employee_id": employee_id, "leave_type_id": type_id, "start_date": start.isoformat(),
                                     "end_date": (start + timedelta(days=days - 1)).isoformat(), "days": days, "half_day": 0,
                                     "reason": "Family function" if type_id == cl["id"] else "Fever", "status": status,
                                     "approver_employee_id": employee["manager_id"], "created_at": db.now_iso()})
    from . import service_desk

    service_desk.create(db.fetch_one("SELECT * FROM employees WHERE id = ?", (ids[2],)), kind="reimbursement", subject="",
                        category="Internet & phone", amount=999, description="October broadband bill")
    service_desk.create(db.fetch_one("SELECT * FROM employees WHERE id = ?", (ids[4],)), kind="ticket", category="IT & access",
                        subject="VPN access for analytics warehouse", description="I need VPN access to query the warehouse from home.")
    for employee_id, period, rating in ((ids[1], "12m", 4.5), (ids[2], "12m", 3.5), (ids[3], "12m", 4.0), (ids[4], "6m", 3.8)):
        db.insert("performance_reviews", {"employee_id": employee_id, "period": period, "rating": rating,
                                          "competencies": {"Domain knowledge": rating, "Communication": max(1, rating - 0.5)},
                                          "notes": "Demo review.", "reviewer": "demo", "created_at": db.now_iso()})
    last_month = today.replace(day=1) - timedelta(days=1)
    payroll.run_payroll(f"{last_month.year}-{last_month.month:02d}", actor="demo")
