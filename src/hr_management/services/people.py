"""Core employee management: directory, profiles, HR edits, self-service edits, manual
creation (for existing staff), HR staff accounts and exit.

Sensitive fields (PAN, bank account) are masked everywhere except the employee's own
"show" view and HR's profile view; edits to them are audit-logged.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import db, notifications
from ..settings import get_settings
from . import ServiceError
from .accounts import create_account, next_user_id

EMPLOYEE_STATUSES = ("probation", "active", "notice", "exited")
HR_EDITABLE = ("designation", "department", "manager_id", "work_location", "employment_type", "status", "probation_end",
               "exit_date", "phone", "date_of_joining")
SELF_EDITABLE = ("phone", "address", "emergency_contact_name", "emergency_contact_phone", "linkedin", "blood_group", "skills")


def mask(value: str, keep: int = 4) -> str:
    value = value or ""
    return value if len(value) <= keep else "•" * (len(value) - keep) + value[-keep:]


def get(employee_id: int) -> dict:
    row = db.fetch_one(
        """SELECT e.*, m.full_name AS manager_name, m.employee_code AS manager_code, a.user_id, a.role AS account_role,
                  a.is_active AS account_active, a.last_login_at
           FROM employees e LEFT JOIN employees m ON m.id = e.manager_id LEFT JOIN accounts a ON a.id = e.account_id
           WHERE e.id = ?""", (employee_id,))
    if not row:
        raise ServiceError("Employee not found.", 404)
    return row


def view(employee: dict, *, reveal: bool = False) -> dict:
    data = dict(employee)
    if not reveal:
        data["pan_number"] = mask(data.get("pan_number", ""))
        data["bank_account_number"] = mask(data.get("bank_account_number", ""))
    data["tenure_days"] = (date.today() - date.fromisoformat(employee["date_of_joining"])).days
    data["reports"] = db.fetch_all("SELECT id, employee_code, full_name, designation FROM employees WHERE manager_id = ? AND status != 'exited' ORDER BY full_name",
                                   (employee["id"],))
    return data


def directory(*, q: str = "", department: str = "", status: str = "") -> list[dict]:
    where, params = ["1 = 1"], []
    if q:
        where.append("(LOWER(e.full_name) LIKE ? OR LOWER(e.email) LIKE ? OR LOWER(e.employee_code) LIKE ? OR LOWER(e.designation) LIKE ?)")
        params += [f"%{q.lower()}%"] * 4
    if department:
        where.append("e.department = ?"); params.append(department)
    if status:
        where.append("e.status = ?"); params.append(status)
    return db.fetch_all(
        f"""SELECT e.id, e.employee_code, e.full_name, e.email, e.phone, e.designation, e.department, e.status,
                   e.date_of_joining, e.work_location, e.manager_id, m.full_name AS manager_name, e.skills
            FROM employees e LEFT JOIN employees m ON m.id = e.manager_id
            WHERE {' AND '.join(where)} ORDER BY e.full_name""", tuple(params))


def departments() -> list[str]:
    rows = db.fetch_all("SELECT DISTINCT department FROM employees WHERE department != '' UNION SELECT DISTINCT department FROM job_openings WHERE department != ''")
    return sorted({row["department"] for row in rows})


def update_by_hr(employee_id: int, changes: dict, *, actor: dict) -> dict:
    employee = get(employee_id)
    fields = {key: changes[key] for key in HR_EDITABLE if key in changes}
    if "status" in fields and fields["status"] not in EMPLOYEE_STATUSES:
        raise ServiceError("Unknown status.")
    if "manager_id" in fields:
        manager_id = int(fields["manager_id"]) if fields["manager_id"] not in (None, "", 0, "0") else None
        if manager_id == employee_id:
            raise ServiceError("An employee cannot report to themselves.")
        if manager_id:
            chain, current = set(), manager_id
            while current:  # prevent reporting loops
                if current == employee_id:
                    raise ServiceError("That would create a reporting loop.")
                if current in chain:
                    break
                chain.add(current)
                row = db.fetch_one("SELECT manager_id FROM employees WHERE id = ?", (current,))
                current = row["manager_id"] if row else None
        fields["manager_id"] = manager_id
        # pending leave now routes to the new manager
        db.execute("UPDATE leave_requests SET approver_employee_id = ? WHERE employee_id = ? AND status = 'pending'", (manager_id, employee_id))
    for key in ("date_of_joining", "probation_end", "exit_date"):
        if fields.get(key):
            try:
                date.fromisoformat(fields[key])
            except ValueError as exc:
                raise ServiceError(f"{key.replace('_', ' ').title()} must be a valid date.") from exc
    fields = {k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items()}
    if not fields:
        return view(employee, reveal=True)
    fields["updated_at"] = db.now_iso()
    db.update("employees", employee_id, fields)
    if fields.get("status") == "exited" and employee.get("account_id"):
        account = db.fetch_one("SELECT * FROM accounts WHERE id = ?", (employee["account_id"],))
        if account:
            db.update("accounts", account["id"], {"is_active": 0, "session_version": int(account["session_version"]) + 1})
    if "manager_id" in fields and fields["manager_id"]:
        manager = db.fetch_one("SELECT account_id FROM employees WHERE id = ?", (fields["manager_id"],))
        notifications.notify(manager and manager["account_id"], "New team member",
                             f"{employee['full_name']} now reports to you.", "/me#/team")
    db.audit(actor["user_id"], "employee_updated", "employee", employee_id, {k: v for k, v in fields.items() if k != "updated_at"})
    return view(get(employee_id), reveal=True)


def update_self(employee: dict, changes: dict) -> dict:
    fields = {}
    for key in SELF_EDITABLE:
        if key not in changes:
            continue
        if key == "skills":
            skills = changes["skills"]
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",")]
            fields["skills"] = [str(s).strip()[:60] for s in skills if str(s).strip()][:50]
        else:
            fields[key] = str(changes[key] or "").strip()[:300]
    if not fields:
        raise ServiceError("Nothing to update.")
    fields["updated_at"] = db.now_iso()
    db.update("employees", employee["id"], fields)
    db.audit(employee["employee_code"], "profile_updated", "employee", employee["id"], {"fields": sorted(fields)})
    return view(get(employee["id"]), reveal=True)


def create_manual(data: dict, *, actor: dict) -> tuple[dict, str]:
    """HR adds an existing employee who was not hired through the portal."""
    from . import payroll

    email = db.normalize_email(data.get("email", ""))
    name = (data.get("full_name") or "").strip()
    if not email or "@" not in email or len(name) < 2:
        raise ServiceError("Full name and a valid email are required.")
    if db.fetch_one("SELECT id FROM employees WHERE email = ?", (email,)):
        raise ServiceError("An employee with this email already exists.", 409)
    joining = data.get("date_of_joining") or date.today().isoformat()
    try:
        joined = date.fromisoformat(joining)
    except ValueError as exc:
        raise ServiceError("Date of joining must be a valid date.") from exc
    probation_end = (joined + timedelta(days=30 * get_settings().probation_months)).isoformat()
    status = "probation" if probation_end > date.today().isoformat() else "active"
    stamp = db.now_iso()
    code = next_user_id("employee")
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    employee_id = db.insert("employees", {
        "employee_code": code, "full_name": name, "email": email, "phone": (data.get("phone") or "").strip(),
        "designation": (data.get("designation") or "").strip(), "department": (data.get("department") or "").strip(),
        "manager_id": int(data["manager_id"]) if str(data.get("manager_id") or "").isdigit() else None,
        "date_of_joining": joining, "employment_type": data.get("employment_type") or "Full-time",
        "work_location": (data.get("work_location") or "").strip(), "status": status, "probation_end": probation_end,
        "skills": skills, "annual_ctc": float(data.get("annual_ctc") or 0), "created_at": stamp, "updated_at": stamp,
    })
    account, password = create_account(email=email, full_name=name, role="employee", employee_id=employee_id, user_id=code)
    db.update("employees", employee_id, {"account_id": account["id"]})
    if float(data.get("annual_ctc") or 0) > 0:
        payroll.save_structure(employee_id, float(data["annual_ctc"]), effective_from=joining, actor=actor["user_id"])
    notifications.send_template("welcome_credentials", email, name=name.split(" ")[0], employee_code=code,
                                user_id=account["user_id"], password=password)
    db.audit(actor["user_id"], "employee_created_manually", "employee", employee_id, {"code": code})
    return get(employee_id), password


def create_hr_user(data: dict, *, actor: dict) -> tuple[dict, str]:
    role = data.get("role") if data.get("role") in {"hr", "hr_admin"} else "hr"
    if role == "hr_admin" and actor["role"] != "hr_admin":
        raise ServiceError("Only an HR administrator can create another administrator.", 403)
    email = db.normalize_email(data.get("email", ""))
    name = (data.get("full_name") or "").strip()
    if not email or "@" not in email or len(name) < 2:
        raise ServiceError("Full name and a valid email are required.")
    employee = db.fetch_one("SELECT id FROM employees WHERE email = ?", (email,))
    account, password = create_account(email=email, full_name=name, role=role, employee_id=employee["id"] if employee else None)
    notifications.send_template("staff_credentials", email, name=name.split(" ")[0], user_id=account["user_id"], password=password)
    db.audit(actor["user_id"], "hr_user_created", "account", account["id"], {"role": role})
    return account, password


def upcoming_events(days: int = 30) -> dict:
    """Birthdays, work anniversaries and probation ends in the next N days (HR dashboard)."""
    today = date.today()
    horizon = today + timedelta(days=days)
    birthdays, anniversaries, probation = [], [], []
    for e in db.fetch_all("SELECT id, employee_code, full_name, date_of_birth, date_of_joining, probation_end, status FROM employees WHERE status != 'exited'"):
        for label, value, bucket in (("birthday", e["date_of_birth"], birthdays), ("anniversary", e["date_of_joining"], anniversaries)):
            if not value:
                continue
            try:
                original = date.fromisoformat(value)
                this_year = original.replace(year=today.year)
            except ValueError:
                continue
            if this_year < today:
                this_year = this_year.replace(year=today.year + 1)
            if this_year <= horizon and (label == "birthday" or this_year.year > original.year):
                bucket.append({"employee": e["full_name"], "code": e["employee_code"], "date": this_year.isoformat(),
                               "years": this_year.year - original.year if label == "anniversary" else None})
        if e["status"] == "probation" and e["probation_end"] and today.isoformat() <= e["probation_end"] <= horizon.isoformat():
            probation.append({"employee": e["full_name"], "code": e["employee_code"], "date": e["probation_end"], "id": e["id"]})
    key = lambda item: item["date"]  # noqa: E731
    return {"birthdays": sorted(birthdays, key=key), "anniversaries": sorted(anniversaries, key=key), "probation_ends": sorted(probation, key=key)}
