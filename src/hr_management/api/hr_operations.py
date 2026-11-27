"""HR → Operations: leave approvals and setup, holidays, attendance, payroll, service desk, policies."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from .. import auth, db, storage
from ..services import ServiceError, attendance, documents, leave, payroll, policies, service_desk

router = APIRouter(prefix="/api/hr", tags=["hr-operations"])


# ---- leave -------------------------------------------------------------------------------

@router.get("/leave")
def leave_queue(status: str = "pending", account: dict = Depends(auth.require_hr)) -> dict:
    return {"requests": leave.list_requests(status=status if status != "all" else ""), "types": leave.leave_types(active_only=False)}


@router.post("/leave/{request_id}/decision")
def decide_leave(request_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"request": leave.decide(request_id, approve=bool(payload.get("approve")), actor=account, note=str(payload.get("note") or ""))}


@router.put("/leave/types/{type_id}")
def update_leave_type(type_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    fields = {}
    for key in ("annual_quota", "min_notice_days", "max_consecutive_days"):
        if key in payload:
            try:
                fields[key] = max(0.0, float(payload[key]))
            except (TypeError, ValueError) as exc:
                raise ServiceError(f"{key.replace('_', ' ')} must be a number.") from exc
    for key in ("paid", "carry_forward", "allow_half_day", "allowed_in_probation", "active"):
        if key in payload:
            fields[key] = int(bool(payload[key]))
    if "description" in payload:
        fields["description"] = str(payload["description"])[:500]
    if not db.update("leave_types", type_id, fields):
        raise HTTPException(status_code=404, detail="Leave type not found.")
    db.audit(account["user_id"], "leave_type_updated", "leave_type", type_id, fields)
    return {"types": leave.leave_types(active_only=False)}


@router.get("/holidays")
def holidays(account: dict = Depends(auth.require_hr)) -> dict:
    return {"holidays": db.fetch_all("SELECT * FROM holidays ORDER BY holiday_date")}


@router.post("/holidays")
def add_holiday(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    from datetime import date

    try:
        day = date.fromisoformat(str(payload.get("date") or "")).isoformat()
    except ValueError as exc:
        raise ServiceError("Choose a valid date.") from exc
    name = str(payload.get("name") or "").strip()[:80]
    if not name:
        raise ServiceError("Give the holiday a name.")
    if db.fetch_one("SELECT id FROM holidays WHERE holiday_date = ?", (day,)):
        raise ServiceError("There is already a holiday on that date.", 409)
    db.insert("holidays", {"holiday_date": day, "name": name})
    db.audit(account["user_id"], "holiday_added", "holiday", day)
    return holidays(account)


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    db.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    return holidays(account)


# ---- attendance --------------------------------------------------------------------------

@router.get("/attendance")
def attendance_day(day: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    return attendance.day_overview(day or None)


@router.get("/attendance/{employee_id}")
def attendance_month(employee_id: int, year: int, month: int, account: dict = Depends(auth.require_hr)) -> dict:
    emp = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return attendance.month_view(emp, year, month)


# ---- payroll -----------------------------------------------------------------------------

@router.get("/payroll")
def payroll_overview(period: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    periods = [r["period"] for r in db.fetch_all("SELECT DISTINCT period FROM payslips ORDER BY period DESC LIMIT 24")]
    period = period or (periods[0] if periods else "")
    slips = db.fetch_all(
        """SELECT p.id, p.period, p.gross, p.total_deductions, p.net_pay, p.lop_days, p.paid_days, p.working_days,
                  e.full_name, e.employee_code, e.department FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE p.period = ? ORDER BY e.full_name""", (period,)) if period else []
    structures = db.fetch_all(
        """SELECT e.id, e.employee_code, e.full_name, e.designation, e.annual_ctc,
                  (SELECT monthly_tds FROM salary_structures s WHERE s.employee_id = e.id ORDER BY s.effective_from DESC, s.id DESC LIMIT 1) AS monthly_tds
           FROM employees e WHERE e.status != 'exited' ORDER BY e.full_name""")
    totals = {k: round(sum(float(s[k]) for s in slips), 2) for k in ("gross", "total_deductions", "net_pay")}
    return {"period": period, "periods": periods, "payslips": slips, "totals": totals, "structures": structures}


@router.post("/payroll/run")
def run_payroll(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return payroll.run_payroll(str(payload.get("period") or ""), actor=account["user_id"])


@router.get("/payslips/{payslip_id}/view", response_class=HTMLResponse)
def view_payslip(payslip_id: int, account: dict = Depends(auth.require_hr)) -> HTMLResponse:
    slip = db.fetch_one("SELECT * FROM payslips WHERE id = ?", (payslip_id,))
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found.")
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (slip["employee_id"],))
    return HTMLResponse(documents.payslip_html(slip, employee), headers={"Cache-Control": "no-store"})


# ---- service desk ------------------------------------------------------------------------

@router.get("/requests")
def requests(status: str = "active", kind: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    return {"requests": service_desk.list_for(status=status if status != "all" else "", kind=kind), "kinds": service_desk.KINDS}


@router.get("/requests/{request_id}")
def request_detail(request_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    return {"request": service_desk.get(request_id)}


@router.post("/requests/{request_id}/resolve")
def resolve_request(request_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"request": service_desk.resolve(request_id, status=str(payload.get("status") or ""), resolution=str(payload.get("resolution") or ""), actor=account)}


@router.post("/requests/{request_id}/comments")
def request_comment(request_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"request": service_desk.comment(request_id, author=account["full_name"], author_role="hr", body=str(payload.get("body") or ""))}


@router.get("/requests/{request_id}/attachment")
def request_attachment(request_id: int, account: dict = Depends(auth.require_hr)) -> Response:
    request = service_desk.get(request_id)
    if not request.get("attachment_key"):
        raise HTTPException(status_code=404, detail="No attachment.")
    return Response(storage.get(request["attachment_key"]), media_type=storage.content_type(request["attachment_key"]))


# ---- policies ----------------------------------------------------------------------------

@router.get("/policies")
def policy_list(account: dict = Depends(auth.require_hr)) -> dict:
    return {"policies": policies.all_policies()}


@router.post("/policies")
def policy_create(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"policy": policies.save(title=payload.get("title", ""), category=payload.get("category", ""), body=payload.get("body", ""), actor=account["user_id"])}


@router.put("/policies/{policy_id}")
def policy_update(policy_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"policy": policies.save(title=payload.get("title", ""), category=payload.get("category", ""), body=payload.get("body", ""),
                                    actor=account["user_id"], policy_id=policy_id)}


@router.delete("/policies/{policy_id}")
def policy_delete(policy_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    policies.delete(policy_id, account["user_id"])
    return {"ok": True}
