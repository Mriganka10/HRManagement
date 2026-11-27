"""Attendance: web check-in/check-out, monthly calendar, HR day view, corrections.

Times are recorded in the company time zone (HRM_TIMEZONE, default Asia/Kolkata).
A check-in later than HRM_OFFICE_START_TIME + HRM_LATE_GRACE_MINUTES is marked ``late``.
Corrections are raised as service requests (kind ``attendance_correction``); when HR
resolves one as approved, ``apply_correction`` writes the corrected record.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from .. import db
from ..settings import company_tz, get_settings
from . import ServiceError


def now_local() -> datetime:
    return datetime.now(company_tz())


def _late_cutoff(day: date) -> datetime:
    cfg = get_settings()
    hour, minute = (int(x) for x in cfg.office_start_time.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=company_tz(cfg.timezone)) + timedelta(minutes=cfg.late_grace_minutes)


def today_record(employee_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?", (employee_id, now_local().date().isoformat()))


def check_in(employee: dict) -> dict:
    now = now_local()
    if now.weekday() >= get_settings().work_week_days:
        raise ServiceError("Today is not a working day.")
    record = today_record(employee["id"])
    if record and record.get("check_in"):
        raise ServiceError(f"You already checked in at {record['check_in'][11:16]}.")
    if record and record["status"] == "on_leave":
        raise ServiceError("You are on approved leave today.")
    status = "late" if now > _late_cutoff(now.date()) else "present"
    if record:
        db.update("attendance", record["id"], {"check_in": now.isoformat(timespec="seconds"), "status": status, "source": "web"})
    else:
        db.insert("attendance", {"employee_id": employee["id"], "work_date": now.date().isoformat(),
                                 "check_in": now.isoformat(timespec="seconds"), "status": status, "source": "web"})
    return today_record(employee["id"])  # type: ignore[return-value]


def check_out(employee: dict) -> dict:
    record = today_record(employee["id"])
    if not record or not record.get("check_in"):
        raise ServiceError("Check in first.")
    if record.get("check_out"):
        raise ServiceError(f"You already checked out at {record['check_out'][11:16]}.")
    now = now_local()
    hours = (now - datetime.fromisoformat(record["check_in"])).total_seconds() / 3600
    fields = {"check_out": now.isoformat(timespec="seconds")}
    if hours < 4:
        fields["status"] = "half_day"
    db.update("attendance", record["id"], fields)
    return today_record(employee["id"])  # type: ignore[return-value]


def month_view(employee: dict, year: int, month: int) -> dict:
    from .leave import holiday_set

    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    rows = {row["work_date"]: row for row in db.fetch_all(
        "SELECT * FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?", (employee["id"], first.isoformat(), last.isoformat()))}
    holidays = {row["holiday_date"]: row["name"] for row in db.fetch_all(
        "SELECT * FROM holidays WHERE holiday_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat()))}
    _ = holiday_set  # same working-day rules as leave
    joined = employee["date_of_joining"]
    today = now_local().date()
    week = get_settings().work_week_days
    days, summary = [], {"present": 0, "late": 0, "half_day": 0, "on_leave": 0, "absent": 0, "holiday": len(holidays)}
    for day in range(1, last.day + 1):
        current = date(year, month, day)
        key = current.isoformat()
        record = rows.get(key)
        if key in holidays:
            status = "holiday"
        elif current.weekday() >= week:
            status = "weekend"
        elif record:
            status = record["status"]
        elif key < joined or current >= today:
            status = "upcoming" if current >= today else "not_joined"
        else:
            status = "absent"
        if status in summary and status != "holiday":
            summary[status] += 1
        hours = None
        if record and record.get("check_in") and record.get("check_out"):
            hours = round((datetime.fromisoformat(record["check_out"]) - datetime.fromisoformat(record["check_in"])).total_seconds() / 3600, 1)
        days.append({"date": key, "weekday": current.strftime("%a"), "status": status, "holiday": holidays.get(key, ""),
                     "check_in": (record or {}).get("check_in"), "check_out": (record or {}).get("check_out"), "hours": hours,
                     "note": (record or {}).get("note", "")})
    return {"year": year, "month": month, "days": days, "summary": summary}


def day_overview(day: str | None = None) -> dict:
    day = day or now_local().date().isoformat()
    employees = db.fetch_all("SELECT id, employee_code, full_name, department, designation FROM employees WHERE status != 'exited' AND date_of_joining <= ? ORDER BY full_name", (day,))
    records = {row["employee_id"]: row for row in db.fetch_all("SELECT * FROM attendance WHERE work_date = ?", (day,))}
    rows, counts = [], {"present": 0, "late": 0, "half_day": 0, "on_leave": 0, "not_marked": 0}
    for employee in employees:
        record = records.get(employee["id"])
        status = record["status"] if record else "not_marked"
        counts[status] = counts.get(status, 0) + 1
        rows.append({**employee, "status": status, "check_in": (record or {}).get("check_in"), "check_out": (record or {}).get("check_out")})
    return {"date": day, "counts": counts, "rows": rows}


def apply_correction(employee_id: int, payload: dict, *, actor: str) -> None:
    """Write the corrected attendance for an approved correction request."""
    work_date = str(payload.get("date") or "")
    try:
        day = date.fromisoformat(work_date)
    except ValueError as exc:
        raise ServiceError("The correction has an invalid date.") from exc
    tz = company_tz()

    def at(value: str) -> str | None:
        if not value:
            return None
        hour, minute = (int(x) for x in value.split(":")[:2])
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).isoformat(timespec="seconds")

    fields = {"check_in": at(payload.get("check_in", "")), "check_out": at(payload.get("check_out", "")),
              "status": "present", "source": "correction", "note": f"Corrected by {actor}"}
    existing = db.fetch_one("SELECT id FROM attendance WHERE employee_id = ? AND work_date = ?", (employee_id, day.isoformat()))
    if existing:
        db.update("attendance", existing["id"], fields)
    else:
        db.insert("attendance", {"employee_id": employee_id, "work_date": day.isoformat(), **fields})
