"""Payroll: salary structures, monthly payslips and plain-language deduction explanations.

Default structure from annual CTC (common Indian private-sector split; HR can override
the CTC and monthly TDS per employee):

    Basic              40% of monthly CTC
    HRA                50% of Basic
    Employer PF        12% of Basic, on Basic capped at ₹15,000 (part of CTC, not paid out)
    Special allowance  the rest of monthly CTC

Deductions: Employee PF (12% of Basic, same cap), Professional Tax (₹200 when gross > ₹15,000),
TDS (monthly amount HR enters from the employee's tax declaration), Loss of pay for unpaid leave.
Income-tax computation is intentionally NOT automated — it depends on the regime and
declarations; HR enters TDS. See docs/PAYROLL.md.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from .. import db, notifications
from ..settings import get_settings
from . import ServiceError

PF_WAGE_CAP = 15000.0
PF_RATE = 0.12
PROFESSIONAL_TAX = 200.0
PT_THRESHOLD = 15000.0


def inr(value: float) -> str:
    """₹ with Indian digit grouping: 152866.67 -> ₹1,52,866.67."""
    value = round(float(value or 0), 2)
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join(groups + [tail]) if groups else tail
    return f"{sign}₹{text}" + ("" if frac == "00" else f".{frac}")


def _r(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def default_components(annual_ctc: float) -> dict[str, float]:
    monthly = annual_ctc / 12
    basic = monthly * 0.40
    hra = basic * 0.50
    employer_pf = PF_RATE * min(basic, PF_WAGE_CAP)
    special = max(0.0, monthly - basic - hra - employer_pf)
    return {"basic": _r(basic), "hra": _r(hra), "special_allowance": _r(special), "employer_pf": _r(employer_pf),
            "monthly_ctc": _r(monthly)}


def save_structure(employee_id: int, annual_ctc: float, *, monthly_tds: float = 0, effective_from: str = "", actor: str) -> dict:
    if annual_ctc <= 0:
        raise ServiceError("Annual CTC must be more than zero.")
    components = default_components(annual_ctc)
    row_id = db.insert("salary_structures", {
        "employee_id": employee_id, "annual_ctc": float(annual_ctc), "components": components,
        "monthly_tds": max(0.0, float(monthly_tds or 0)), "effective_from": effective_from or date.today().isoformat(),
        "created_by": actor, "created_at": db.now_iso(),
    })
    db.update("employees", employee_id, {"annual_ctc": float(annual_ctc), "updated_at": db.now_iso()})
    db.audit(actor, "salary_structure_saved", "employee", employee_id, {"annual_ctc": annual_ctc})
    return db.fetch_one("SELECT * FROM salary_structures WHERE id = ?", (row_id,))  # type: ignore[return-value]


def current_structure(employee_id: int, on: str | None = None) -> dict | None:
    on = on or date.today().isoformat()
    return db.fetch_one(
        "SELECT * FROM salary_structures WHERE employee_id = ? AND effective_from <= ? ORDER BY effective_from DESC, id DESC LIMIT 1",
        (employee_id, on),
    ) or db.fetch_one("SELECT * FROM salary_structures WHERE employee_id = ? ORDER BY id DESC LIMIT 1", (employee_id,))


def working_days(year: int, month: int, start: date | None = None) -> float:
    """Working days in the month (from ``start`` if the employee joined mid-month), minus holidays."""
    week = get_settings().work_week_days
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    start = max(first, start or first)
    holidays = {row["holiday_date"] for row in db.fetch_all(
        "SELECT holiday_date FROM holidays WHERE holiday_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat()))}
    days, current = 0, start
    while current <= last:
        if current.weekday() < week and current.isoformat() not in holidays:
            days += 1
        current += timedelta(days=1)
    return float(days)


def _unpaid_leave_days(employee_id: int, year: int, month: int) -> float:
    from .leave import days_in_range  # shares the working-day rules

    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    total = 0.0
    rows = db.fetch_all(
        """SELECT lr.* FROM leave_requests lr JOIN leave_types lt ON lt.id = lr.leave_type_id
           WHERE lr.employee_id = ? AND lr.status = 'approved' AND lt.paid = 0 AND lr.start_date <= ? AND lr.end_date >= ?""",
        (employee_id, last.isoformat(), first.isoformat()),
    )
    for row in rows:
        start = max(first, date.fromisoformat(row["start_date"]))
        end = min(last, date.fromisoformat(row["end_date"]))
        total += 0.5 if row["half_day"] else days_in_range(start, end)
    return total


def generate_payslip(employee_id: int, period: str, *, actor: str, extra_lop_days: float = 0) -> dict:
    try:
        year, month = (int(part) for part in period.split("-"))
        first = date(year, month, 1)
    except ValueError as exc:
        raise ServiceError("Period must look like 2026-11.") from exc
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
    if not employee:
        raise ServiceError("Employee not found.", 404)
    last = date(year, month, calendar.monthrange(year, month)[1])
    joined = date.fromisoformat(employee["date_of_joining"])
    if joined > last:
        raise ServiceError(f"{employee['full_name']} joins after {period}.")
    structure = current_structure(employee_id, last.isoformat())
    if not structure:
        raise ServiceError(f"No salary structure for {employee['full_name']}. Set the CTC first.")
    month_days = working_days(year, month)
    eligible_days = working_days(year, month, start=joined if joined > first else None)
    lop = min(eligible_days, _unpaid_leave_days(employee_id, year, month) + max(0.0, float(extra_lop_days or 0)))
    paid_days = max(0.0, eligible_days - lop)
    factor = paid_days / month_days if month_days else 0
    c = structure["components"]
    earnings = {"Basic": _r(c["basic"] * factor), "House Rent Allowance": _r(c["hra"] * factor),
                "Special Allowance": _r(c["special_allowance"] * factor)}
    gross = _r(sum(earnings.values()))
    pf = _r(PF_RATE * min(earnings["Basic"], PF_WAGE_CAP))
    deductions = {"Provident Fund (employee)": pf,
                  "Professional Tax": PROFESSIONAL_TAX if gross > PT_THRESHOLD else 0.0,
                  "Income Tax (TDS)": _r(structure["monthly_tds"] or 0)}
    deductions = {k: v for k, v in deductions.items() if v}
    total_deductions = _r(sum(deductions.values()))
    data = {
        "employee_id": employee_id, "period": period, "working_days": month_days, "paid_days": paid_days,
        "lop_days": lop, "earnings": earnings, "deductions": deductions, "gross": gross,
        "total_deductions": total_deductions, "net_pay": _r(gross - total_deductions), "generated_at": db.now_iso(),
    }
    existing = db.fetch_one("SELECT id FROM payslips WHERE employee_id = ? AND period = ?", (employee_id, period))
    if existing:
        db.update("payslips", existing["id"], data)
        slip_id = existing["id"]
    else:
        slip_id = db.insert("payslips", data)
        notifications.notify(employee.get("account_id"), f"Payslip for {first.strftime('%B %Y')} is ready",
                             f"Net pay {inr(data['net_pay'])}", "/me#/payslips")
    db.audit(actor, "payslip_generated", "employee", employee_id, {"period": period})
    return db.fetch_one("SELECT * FROM payslips WHERE id = ?", (slip_id,))  # type: ignore[return-value]


def run_payroll(period: str, *, actor: str) -> dict:
    """Generate payslips for every active employee for the month."""
    done, skipped = [], []
    for employee in db.fetch_all("SELECT id, full_name FROM employees WHERE status != 'exited' ORDER BY id"):
        try:
            generate_payslip(employee["id"], period, actor=actor)
            done.append(employee["full_name"])
        except ServiceError as exc:
            skipped.append({"employee": employee["full_name"], "reason": exc.message})
    return {"period": period, "generated": len(done), "skipped": skipped}


def explain(payslip: dict) -> list[str]:
    """Plain-language explanation of each line, used by the portal and the AI assistant."""
    lines = [f"You were paid for {payslip['paid_days']:g} of {payslip['working_days']:g} working days."]
    if payslip["lop_days"]:
        lines.append(f"{payslip['lop_days']:g} day(s) were loss of pay (approved unpaid leave or HR adjustment), "
                     "so every earning was reduced in proportion.")
    for name, amount in (payslip.get("deductions") or {}).items():
        if name.startswith("Provident"):
            lines.append(f"Provident Fund {inr(amount)}: 12% of your Basic (on Basic up to ₹15,000). It goes to your EPF account "
                         "and the company adds the same amount as employer contribution (part of your CTC).")
        elif name.startswith("Professional"):
            lines.append(f"Professional Tax {inr(amount)}: a state tax on employment, deducted when monthly gross is above ₹15,000.")
        elif "TDS" in name:
            lines.append(f"Income Tax (TDS) {inr(amount)}: tax deducted at source based on your projected annual income and "
                         "the declarations you submitted to HR. Raise an HR request if your declarations changed.")
    lines.append(f"Net pay = gross {inr(payslip['gross'])} − deductions {inr(payslip['total_deductions'])} = {inr(payslip['net_pay'])}.")
    return lines
