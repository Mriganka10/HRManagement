"""Employee portal API (/api/me): home, profile, leave, team approvals (managers), attendance,
payslips, HR requests, documents, policies, growth, notifications and the AI assistant."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from .. import auth, db, i18n
from ..engines.guardrails import enforce as enforce_limit
from ..services import (
    ServiceError, assistant, attendance, documents, leave, payroll, people, performance, policies, service_desk, talent,
)

router = APIRouter(prefix="/api/me", tags=["employee"])


def me(account: dict = Depends(auth.require_employee)) -> dict:
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (account["employee_id"],))
    if not employee:
        raise HTTPException(status_code=403, detail="Employee profile not found.")
    if employee["status"] == "exited":
        raise HTTPException(status_code=403, detail="This employee account is closed.")
    return {**employee, "_account": account}


@router.get("/home")
def home(employee: dict = Depends(me)) -> dict:
    today = attendance.now_local().date()
    pending_team = leave.list_requests(approver_employee_id=employee["id"], status="pending")
    return {
        "profile": people.view(people.get(employee["id"])),
        "today": attendance.today_record(employee["id"]),
        "is_working_day": today.weekday() < 5,
        "balances": leave.balances(employee),
        "my_pending_leave": leave.list_requests(employee_id=employee["id"], status="pending"),
        "open_requests": service_desk.list_for(employee_id=employee["id"], status="active")[:5],
        "team_pending": len(pending_team),
        "latest_payslip": db.fetch_one("SELECT id, period, net_pay FROM payslips WHERE employee_id = ? ORDER BY period DESC LIMIT 1", (employee["id"],)),
        "holidays": db.fetch_all("SELECT * FROM holidays WHERE holiday_date >= ? ORDER BY holiday_date LIMIT 4", (today.isoformat(),)),
        "month": attendance.month_view(employee, today.year, today.month)["summary"],
        "notifications": db.fetch_all("SELECT * FROM notifications WHERE account_id = ? ORDER BY id DESC LIMIT 8", (employee["_account"]["id"],)),
    }


# ---- profile -----------------------------------------------------------------------------

@router.get("/profile")
def profile(reveal: bool = False, employee: dict = Depends(me)) -> dict:
    return {"profile": people.view(people.get(employee["id"]), reveal=reveal), "self_editable": list(people.SELF_EDITABLE)}


@router.put("/profile")
def update_profile(payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return {"profile": people.update_self(employee, payload)}


# ---- leave -------------------------------------------------------------------------------

@router.get("/leave")
def my_leave(employee: dict = Depends(me)) -> dict:
    return {"balances": leave.balances(employee), "requests": leave.list_requests(employee_id=employee["id"], limit=50),
            "types": leave.leave_types(), "holidays": db.fetch_all("SELECT * FROM holidays ORDER BY holiday_date")}


@router.post("/leave/check")
def check_leave(payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return leave.check_eligibility(employee, payload.get("leave_type"), str(payload.get("start_date") or ""),
                                   str(payload.get("end_date") or payload.get("start_date") or ""), half_day=bool(payload.get("half_day")))


@router.post("/leave")
def apply_leave(payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return {"request": leave.apply(employee, leave_type_ref=payload.get("leave_type"), start_date=str(payload.get("start_date") or ""),
                                   end_date=str(payload.get("end_date") or payload.get("start_date") or ""),
                                   half_day=bool(payload.get("half_day")), reason=str(payload.get("reason") or ""))}


@router.post("/leave/{request_id}/cancel")
def cancel_leave(request_id: int, employee: dict = Depends(me)) -> dict:
    return {"request": leave.cancel(request_id, employee)}


# ---- team (reporting managers) -----------------------------------------------------------

@router.get("/team")
def team(employee: dict = Depends(me)) -> dict:
    reports = db.fetch_all("SELECT id, employee_code, full_name, designation, date_of_joining, status FROM employees WHERE manager_id = ? AND status != 'exited' ORDER BY full_name",
                           (employee["id"],))
    today = attendance.now_local().date().isoformat()
    for r in reports:
        rec = db.fetch_one("SELECT status, check_in FROM attendance WHERE employee_id = ? AND work_date = ?", (r["id"], today))
        r["today"] = rec["status"] if rec else "not_marked"
        r["reviews"] = performance.reviews_for(r["id"])[:3]
    return {"reports": reports, "pending": leave.list_requests(approver_employee_id=employee["id"], status="pending"),
            "history": leave.list_requests(approver_employee_id=employee["id"], limit=30),
            "due_reviews": [d for d in performance.due_reviews() if d["manager_id"] == employee["id"]]}


@router.post("/team/leave/{request_id}/decision")
def team_decide(request_id: int, payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return {"request": leave.decide(request_id, approve=bool(payload.get("approve")), actor=employee["_account"], note=str(payload.get("note") or ""))}


@router.post("/team/{employee_id}/reviews")
def team_review(employee_id: int, payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return {"review": performance.save_review(employee_id, period=str(payload.get("period") or ""), rating=float(payload.get("rating") or 0),
                                              competencies=payload.get("competencies") or {}, notes=str(payload.get("notes") or ""),
                                              actor=employee["_account"])}


# ---- attendance --------------------------------------------------------------------------

@router.get("/attendance")
def my_attendance(year: int = 0, month: int = 0, employee: dict = Depends(me)) -> dict:
    today = attendance.now_local().date()
    return {**attendance.month_view(employee, year or today.year, month or today.month), "today": attendance.today_record(employee["id"])}


@router.post("/attendance/check-in")
def check_in(employee: dict = Depends(me)) -> dict:
    return {"today": attendance.check_in(employee)}


@router.post("/attendance/check-out")
def check_out(employee: dict = Depends(me)) -> dict:
    return {"today": attendance.check_out(employee)}


# ---- payslips ----------------------------------------------------------------------------

@router.get("/payslips")
def payslips(employee: dict = Depends(me)) -> dict:
    slips = db.fetch_all("SELECT * FROM payslips WHERE employee_id = ? ORDER BY period DESC", (employee["id"],))
    for slip in slips:
        slip["explanation"] = payroll.explain(slip)
    structure = payroll.current_structure(employee["id"])
    return {"payslips": slips, "structure": structure}


@router.get("/payslips/{payslip_id}/view", response_class=HTMLResponse)
def view_payslip(payslip_id: int, employee: dict = Depends(me)) -> HTMLResponse:
    slip = db.fetch_one("SELECT * FROM payslips WHERE id = ? AND employee_id = ?", (payslip_id, employee["id"]))
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found.")
    return HTMLResponse(documents.payslip_html(slip, employee), headers={"Cache-Control": "no-store"})


# ---- HR requests -------------------------------------------------------------------------

@router.get("/requests")
def my_requests(employee: dict = Depends(me)) -> dict:
    return {"requests": service_desk.list_for(employee_id=employee["id"]), "kinds": service_desk.KINDS,
            "ticket_categories": service_desk.TICKET_CATEGORIES, "reimbursement_categories": service_desk.REIMBURSEMENT_CATEGORIES,
            "document_types": service_desk.DOCUMENT_TYPES}


@router.post("/requests")
async def create_request(
    kind: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    work_date: Annotated[str, Form()] = "",
    check_in_time: Annotated[str, Form()] = "",
    check_out_time: Annotated[str, Form()] = "",
    last_working_day: Annotated[str, Form()] = "",
    attachment: UploadFile | None = File(default=None),
    employee: dict = Depends(me),
) -> dict:
    payload = {}
    if kind == "attendance_correction":
        payload = {"date": work_date, "check_in": check_in_time, "check_out": check_out_time}
    elif kind == "document":
        payload = {"document_type": category}
    elif kind == "exit":
        payload = {"last_working_day": last_working_day}
    try:
        value = float(amount) if amount else None
    except ValueError as exc:
        raise ServiceError("Amount must be a number.") from exc
    file = (attachment.filename or "attachment", await attachment.read()) if attachment and attachment.filename else None
    return {"request": service_desk.create(employee, kind=kind, subject=subject, description=description, category=category,
                                           amount=value, payload=payload, attachment=file)}


@router.get("/requests/{request_id}")
def request_detail(request_id: int, employee: dict = Depends(me)) -> dict:
    request = service_desk.get(request_id)
    if request["employee_id"] != employee["id"]:
        raise HTTPException(status_code=404, detail="Request not found.")
    return {"request": request}


@router.post("/requests/{request_id}/comments")
def request_comment(request_id: int, payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    if service_desk.get(request_id)["employee_id"] != employee["id"]:
        raise HTTPException(status_code=404, detail="Request not found.")
    return {"request": service_desk.comment(request_id, author=employee["full_name"], author_role="employee", body=str(payload.get("body") or ""))}


@router.post("/requests/{request_id}/cancel")
def request_cancel(request_id: int, employee: dict = Depends(me)) -> dict:
    return {"request": service_desk.cancel(request_id, employee)}


# ---- documents, policies, growth, notifications -------------------------------------------

@router.get("/documents")
def my_documents(employee: dict = Depends(me)) -> dict:
    return {"documents": documents.for_employee(employee["id"])}


@router.get("/documents/{doc_id}")
def read_document(doc_id: int, employee: dict = Depends(me)) -> Response:
    doc, data = documents.read(doc_id, employee["id"])
    return Response(data, media_type=doc["content_type"] if "charset" in doc["content_type"] else f"{doc['content_type']}; charset=utf-8")


@router.get("/policies")
def policy_list(employee: dict = Depends(me)) -> dict:
    return {"policies": policies.all_policies()}


@router.get("/growth")
def growth(employee: dict = Depends(me)) -> dict:
    return {"skill_gap": talent.gap_for_employee(employee), "internal_roles": talent.internal_matches(employee),
            "reviews": performance.reviews_for(employee["id"]), "skills": employee["skills"]}


@router.get("/notifications")
def notifications(employee: dict = Depends(me)) -> dict:
    account_id = employee["_account"]["id"]
    return {"notifications": db.fetch_all("SELECT * FROM notifications WHERE account_id = ? ORDER BY id DESC LIMIT 50", (account_id,)),
            "unread": int((db.fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE account_id = ? AND is_read = 0", (account_id,)) or {}).get("n", 0))}


@router.post("/notifications/read")
def mark_read(employee: dict = Depends(me)) -> dict:
    db.execute("UPDATE notifications SET is_read = 1 WHERE account_id = ?", (employee["_account"]["id"],))
    return {"ok": True}


# ---- AI assistant ------------------------------------------------------------------------

@router.post("/assistant")
def ask(request: Request, payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    enforce_limit("assistant", employee["employee_code"])
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    return assistant.respond(employee, str(payload.get("message") or ""), history[-10:], lang=i18n.request_lang(request))


@router.post("/assistant/confirm")
def confirm(request: Request, payload: Annotated[dict, Body()], employee: dict = Depends(me)) -> dict:
    return assistant.execute(employee, payload.get("action") or {}, lang=i18n.request_lang(request))
