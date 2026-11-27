"""Leave management: types, balances, eligibility, apply → route to manager → approve/reject.

Rules applied by ``check_eligibility`` (the same check the AI assistant runs before it
offers to apply):
- dates valid, not in the past, end ≥ start; only working days are counted (weekends per
  HRM_WORK_WEEK_DAYS and company holidays are skipped)
- minimum notice and maximum consecutive days per leave type
- type allowed during probation
- no overlap with another pending/approved request
- enough balance (paid types). Balance = annual quota pro-rated from the joining date
  in the current calendar year − approved − pending days.
Approval goes to the reporting manager; if the employee has none, to HR.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import db, notifications
from ..settings import get_settings
from . import ServiceError

DEFAULT_TYPES = [
    # code, name, quota, paid, carry, notice, max_consecutive, half_day, in_probation, description
    ("CL", "Casual Leave", 8, 1, 0, 1, 3, 1, 1, "Short personal needs. Apply at least a day ahead; up to 3 days at a time."),
    ("SL", "Sick Leave", 8, 1, 0, 0, 7, 1, 1, "Illness. Can be applied on the same day. A medical certificate may be requested for more than 2 days."),
    ("EL", "Earned Leave", 15, 1, 1, 7, 15, 0, 0, "Planned vacations. Apply 7 days ahead. Available after probation."),
    ("WFH", "Work From Home", 24, 1, 0, 1, 5, 1, 1, "Working remotely for a day. Counts toward attendance as present."),
    ("LWP", "Leave Without Pay", 30, 0, 0, 0, 30, 1, 1, "Unpaid leave when other balances are exhausted. Reduces salary for those days."),
]


def seed_defaults() -> None:
    if db.fetch_one("SELECT id FROM leave_types LIMIT 1"):
        return
    for code, name, quota, paid, carry, notice, max_days, half, probation, description in DEFAULT_TYPES:
        db.insert("leave_types", {"code": code, "name": name, "annual_quota": quota, "paid": paid, "carry_forward": carry,
                                  "min_notice_days": notice, "max_consecutive_days": max_days, "allow_half_day": half,
                                  "allowed_in_probation": probation, "description": description, "active": 1})
    year = date.today().year
    for month_day, name in (("01-26", "Republic Day"), ("08-15", "Independence Day"), ("10-02", "Gandhi Jayanti"),
                            ("12-25", "Christmas")):
        for y in (year, year + 1):
            try:
                db.insert("holidays", {"holiday_date": f"{y}-{month_day}", "name": name})
            except Exception:
                pass


def leave_types(active_only: bool = True) -> list[dict]:
    return db.fetch_all("SELECT * FROM leave_types" + (" WHERE active = 1" if active_only else "") + " ORDER BY id")


def holiday_set(start: date, end: date) -> set[str]:
    return {row["holiday_date"] for row in db.fetch_all(
        "SELECT holiday_date FROM holidays WHERE holiday_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}


def days_in_range(start: date, end: date) -> float:
    week = get_settings().work_week_days
    holidays = holiday_set(start, end)
    days, current = 0, start
    while current <= end:
        if current.weekday() < week and current.isoformat() not in holidays:
            days += 1
        current += timedelta(days=1)
    return float(days)


def _year_bounds(year: int) -> tuple[str, str]:
    return f"{year}-01-01", f"{year}-12-31"


def entitlement(employee: dict, leave_type: dict, year: int) -> float:
    """Annual quota, pro-rated by months remaining if the employee joined this year."""
    quota = float(leave_type["annual_quota"])
    joined = date.fromisoformat(employee["date_of_joining"])
    if joined.year == year:
        quota = quota * (12 - joined.month + 1) / 12
    elif joined.year > year:
        quota = 0
    return round(quota * 2) / 2  # nearest half day


def balances(employee: dict, year: int | None = None) -> list[dict]:
    year = year or date.today().year
    start, end = _year_bounds(year)
    out = []
    for leave_type in leave_types():
        rows = db.fetch_all(
            "SELECT status, COALESCE(SUM(days), 0) AS total FROM leave_requests WHERE employee_id = ? AND leave_type_id = ? "
            "AND start_date BETWEEN ? AND ? AND status IN ('approved', 'pending') GROUP BY status",
            (employee["id"], leave_type["id"], start, end),
        )
        used = {row["status"]: float(row["total"]) for row in rows}
        entitled = entitlement(employee, leave_type, year)
        out.append({
            "leave_type_id": leave_type["id"], "code": leave_type["code"], "name": leave_type["name"],
            "paid": bool(leave_type["paid"]), "entitled": entitled, "used": used.get("approved", 0.0),
            "pending": used.get("pending", 0.0),
            "available": round(entitled - used.get("approved", 0.0) - used.get("pending", 0.0), 1),
            "description": leave_type["description"],
        })
    return out


def _type_by(code_or_id) -> dict | None:
    if isinstance(code_or_id, int) or str(code_or_id).isdigit():
        return db.fetch_one("SELECT * FROM leave_types WHERE id = ? AND active = 1", (int(code_or_id),))
    return db.fetch_one("SELECT * FROM leave_types WHERE UPPER(code) = ? AND active = 1", (str(code_or_id).upper(),))


def check_eligibility(employee: dict, leave_type_ref, start_date: str, end_date: str, *, half_day: bool = False) -> dict:
    """Returns {eligible, days, problems[], balance} without saving anything."""
    problems: list[str] = []
    leave_type = _type_by(leave_type_ref)
    if not leave_type:
        return {"eligible": False, "days": 0, "problems": ["Unknown leave type."], "leave_type": None}
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date or start_date)
    except ValueError:
        return {"eligible": False, "days": 0, "problems": ["Dates must be valid (YYYY-MM-DD)."], "leave_type": leave_type}
    today = date.today()
    if end < start:
        problems.append("End date is before the start date.")
    if start < today - timedelta(days=7 if leave_type["code"] == "SL" else 0):
        problems.append("Leave cannot start in the past." if leave_type["code"] != "SL" else "Sick leave can be back-dated by up to 7 days only.")
    if half_day:
        if not leave_type["allow_half_day"]:
            problems.append(f"{leave_type['name']} cannot be taken as a half day.")
        if start != end:
            problems.append("A half day must start and end on the same date.")
    days = 0.5 if half_day and start == end else days_in_range(start, end) if end >= start else 0
    if end >= start and days == 0:
        problems.append("The selected dates are all weekends or holidays.")
    if (start - today).days < int(leave_type["min_notice_days"]) and leave_type["code"] != "SL":
        problems.append(f"{leave_type['name']} needs at least {leave_type['min_notice_days']} day(s) notice.")
    if leave_type["max_consecutive_days"] and days > float(leave_type["max_consecutive_days"]):
        problems.append(f"{leave_type['name']} allows at most {leave_type['max_consecutive_days']} working days at a time.")
    in_probation = employee["status"] == "probation" and (employee.get("probation_end") or "9999") > today.isoformat()
    if in_probation and not leave_type["allowed_in_probation"]:
        problems.append(f"{leave_type['name']} is available after your probation ends on {employee.get('probation_end')}.")
    overlap = db.fetch_one(
        "SELECT id, start_date, end_date FROM leave_requests WHERE employee_id = ? AND status IN ('pending', 'approved') "
        "AND start_date <= ? AND end_date >= ?", (employee["id"], end.isoformat(), start.isoformat()))
    if overlap:
        problems.append(f"You already have leave from {overlap['start_date']} to {overlap['end_date']}.")
    balance = next((b for b in balances(employee, start.year) if b["leave_type_id"] == leave_type["id"]), None)
    if balance and leave_type["paid"] and days > balance["available"]:
        problems.append(f"Not enough {leave_type['name']} balance: {balance['available']:g} day(s) available, {days:g} requested.")
    return {"eligible": not problems, "days": days, "problems": problems, "balance": balance,
            "leave_type": {"id": leave_type["id"], "code": leave_type["code"], "name": leave_type["name"]},
            "start_date": start.isoformat(), "end_date": end.isoformat(), "half_day": half_day}


def apply(employee: dict, *, leave_type_ref, start_date: str, end_date: str, half_day: bool = False, reason: str = "") -> dict:
    check = check_eligibility(employee, leave_type_ref, start_date, end_date, half_day=half_day)
    if not check["eligible"]:
        raise ServiceError(" ".join(check["problems"]))
    request_id = db.insert("leave_requests", {
        "employee_id": employee["id"], "leave_type_id": check["leave_type"]["id"], "start_date": check["start_date"],
        "end_date": check["end_date"], "days": check["days"], "half_day": int(half_day), "reason": reason.strip()[:500],
        "status": "pending", "approver_employee_id": employee.get("manager_id"), "created_at": db.now_iso(),
    })
    dates = check["start_date"] if check["start_date"] == check["end_date"] else f"{check['start_date']} to {check['end_date']}"
    manager = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee["manager_id"],)) if employee.get("manager_id") else None
    if manager:
        notifications.notify(manager.get("account_id"), f"Leave request from {employee['full_name']}",
                             f"{check['leave_type']['name']}, {dates} ({check['days']:g} day(s))", "/me#/team")
        notifications.send_template("leave_pending", manager["email"], employee=employee["full_name"],
                                    leave_type=check["leave_type"]["name"], dates=dates, days=f"{check['days']:g}",
                                    reason=reason or "—")
    else:
        notifications.notify_hr(f"Leave request from {employee['full_name']}", f"{check['leave_type']['name']}, {dates}", "/hr#/leave")
    db.audit(employee["employee_code"], "leave_applied", "leave_request", request_id)
    return get_request(request_id)


def get_request(request_id: int) -> dict:
    return db.fetch_one(
        """SELECT lr.*, lt.code AS leave_code, lt.name AS leave_name, e.full_name AS employee_name, e.employee_code,
                  m.full_name AS approver_name
           FROM leave_requests lr JOIN leave_types lt ON lt.id = lr.leave_type_id JOIN employees e ON e.id = lr.employee_id
           LEFT JOIN employees m ON m.id = lr.approver_employee_id WHERE lr.id = ?""", (request_id,)) or {}


def list_requests(*, employee_id: int | None = None, approver_employee_id: int | None = None, status: str = "",
                  hr_queue: bool = False, limit: int = 200) -> list[dict]:
    where, params = [], []
    if employee_id:
        where.append("lr.employee_id = ?"); params.append(employee_id)
    if approver_employee_id:
        where.append("lr.approver_employee_id = ?"); params.append(approver_employee_id)
    if status:
        where.append("lr.status = ?"); params.append(status)
    sql = """SELECT lr.*, lt.code AS leave_code, lt.name AS leave_name, e.full_name AS employee_name, e.employee_code,
                    e.department, m.full_name AS approver_name
             FROM leave_requests lr JOIN leave_types lt ON lt.id = lr.leave_type_id JOIN employees e ON e.id = lr.employee_id
             LEFT JOIN employees m ON m.id = lr.approver_employee_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY lr.created_at DESC LIMIT ?"
    return db.fetch_all(sql, (*params, limit))


def decide(request_id: int, *, approve: bool, actor: dict, note: str = "") -> dict:
    """Approve/reject. Allowed for HR, or the employee's reporting manager (not for own leave)."""
    request = get_request(request_id)
    if not request:
        raise ServiceError("Leave request not found.", 404)
    is_hr = actor["role"] in {"hr", "hr_admin"}
    is_manager = actor.get("employee_id") and request["approver_employee_id"] == actor.get("employee_id")
    if not (is_hr or is_manager):
        raise ServiceError("Only the reporting manager or HR can decide this request.", 403)
    if actor.get("employee_id") == request["employee_id"]:
        raise ServiceError("You cannot approve your own leave.", 403)
    status = "approved" if approve else "rejected"
    if approve:  # balance may have changed since it was applied
        employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (request["employee_id"],))
        leave_type = _type_by(request["leave_type_id"])
        balance = next((b for b in balances(employee, int(request["start_date"][:4])) if b["leave_type_id"] == request["leave_type_id"]), None)
        if leave_type and leave_type["paid"] and balance and balance["available"] < 0:
            raise ServiceError("Approving would make the balance negative.")
    if not db.update("leave_requests", request_id, {"status": status, "decided_by": actor["user_id"], "decided_at": db.now_iso(),
                                                    "decision_note": note.strip()[:500]}, where="status = 'pending'"):
        raise ServiceError("This request was already decided.", 409)
    if approve:
        _mark_attendance_on_leave(request)
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (request["employee_id"],))
    dates = request["start_date"] if request["start_date"] == request["end_date"] else f"{request['start_date']} to {request['end_date']}"
    notifications.notify(employee.get("account_id"), f"Leave {status}", f"{request['leave_name']}, {dates}", "/me#/leave")
    notifications.send_template("leave_decision", employee["email"], name=employee["full_name"].split(" ")[0], decision=status,
                                leave_type=request["leave_name"], days=f"{request['days']:g}", dates=dates,
                                note=f"Note from {actor['full_name']}: {note}" if note else "")
    db.audit(actor["user_id"], f"leave_{status}", "leave_request", request_id)
    return get_request(request_id)


def cancel(request_id: int, employee: dict) -> dict:
    request = get_request(request_id)
    if not request or request["employee_id"] != employee["id"]:
        raise ServiceError("Leave request not found.", 404)
    if request["status"] == "approved" and request["start_date"] <= date.today().isoformat():
        raise ServiceError("Leave that has already started cannot be cancelled. Contact HR.")
    if not db.update("leave_requests", request_id, {"status": "cancelled", "decided_at": db.now_iso()},
                     where="status IN ('pending', 'approved')"):
        raise ServiceError("This request cannot be cancelled.", 409)
    db.execute("DELETE FROM attendance WHERE employee_id = ? AND status = 'on_leave' AND work_date BETWEEN ? AND ?",
               (employee["id"], request["start_date"], request["end_date"]))
    return get_request(request_id)


def _mark_attendance_on_leave(request: dict) -> None:
    start, end = date.fromisoformat(request["start_date"]), date.fromisoformat(request["end_date"])
    holidays = holiday_set(start, end)
    current = start
    while current <= end:
        if current.weekday() < get_settings().work_week_days and current.isoformat() not in holidays:
            status = "present" if request["leave_code"] == "WFH" else "half_day" if request["half_day"] else "on_leave"
            if not db.fetch_one("SELECT id FROM attendance WHERE employee_id = ? AND work_date = ?", (request["employee_id"], current.isoformat())):
                db.insert("attendance", {"employee_id": request["employee_id"], "work_date": current.isoformat(), "status": status,
                                         "source": "leave", "note": request["leave_name"]})
        current += timedelta(days=1)
