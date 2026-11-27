"""HR → People: dashboard, employees (directory, profile, edit, add), HR users,
talent & skills, performance and recruitment intelligence, generated documents."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends

from .. import auth, db
from ..services import accounts, documents, insights, leave, payroll, people, performance, service_desk, talent

router = APIRouter(prefix="/api/hr", tags=["hr-people"])


@router.get("/dashboard")
def dashboard(account: dict = Depends(auth.require_hr)) -> dict:
    return insights.dashboard()


@router.get("/employees")
def employees(q: str = "", department: str = "", status: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    return {"employees": people.directory(q=q, department=department, status=status), "departments": people.departments()}


@router.post("/employees")
def add_employee(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    employee, _ = people.create_manual(payload, actor=account)
    return {"employee": people.view(employee, reveal=True), "message": f"Employee {employee['employee_code']} created; credentials emailed."}


@router.get("/employees/{employee_id}")
def employee(employee_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    emp = people.get(employee_id)
    db.audit(account["user_id"], "employee_viewed", "employee", employee_id)  # profile contains PAN/bank details
    year = db.utcnow().year
    return {
        "employee": people.view(emp, reveal=True),
        "leave_balances": leave.balances(emp, year),
        "leave_requests": leave.list_requests(employee_id=employee_id, limit=20),
        "salary": payroll.current_structure(employee_id),
        "payslips": db.fetch_all("SELECT id, period, net_pay, gross FROM payslips WHERE employee_id = ? ORDER BY period DESC LIMIT 12", (employee_id,)),
        "requests": service_desk.list_for(employee_id=employee_id)[:20],
        "reviews": performance.reviews_for(employee_id),
        "documents": documents.for_employee(employee_id),
        "skill_gap": talent.gap_for_employee(emp),
        "managers": db.fetch_all("SELECT id, full_name, employee_code FROM employees WHERE status != 'exited' AND id != ? ORDER BY full_name", (employee_id,)),
    }


@router.put("/employees/{employee_id}")
def update_employee(employee_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"employee": people.update_by_hr(employee_id, payload, actor=account)}


@router.post("/employees/{employee_id}/salary")
def set_salary(employee_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    structure = payroll.save_structure(employee_id, float(payload.get("annual_ctc") or 0), monthly_tds=float(payload.get("monthly_tds") or 0),
                                       effective_from=str(payload.get("effective_from") or ""), actor=account["user_id"])
    return {"salary": structure}


@router.post("/employees/{employee_id}/documents")
def generate_document(employee_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"document": documents.generate(employee_id, str(payload.get("kind") or ""), actor=account["user_id"])}


@router.post("/employees/{employee_id}/reviews")
def save_review(employee_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    return {"review": performance.save_review(employee_id, period=str(payload.get("period") or ""), rating=float(payload.get("rating") or 0),
                                              competencies=payload.get("competencies") or {}, notes=str(payload.get("notes") or ""), actor=account)}


# ---- accounts ----------------------------------------------------------------------------

@router.get("/accounts")
def account_list(account: dict = Depends(auth.require_hr)) -> dict:
    rows = db.fetch_all("SELECT * FROM accounts ORDER BY role, user_id")
    return {"accounts": [accounts.public(row) | {"locked_until": row.get("locked_until")} for row in rows]}


@router.post("/accounts")
def create_hr_account(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    created, _ = people.create_hr_user(payload, actor=account)
    return {"account": accounts.public(created), "message": f"{created['user_id']} created; credentials emailed."}


@router.post("/accounts/{account_id}/reset-password")
def reset_password(account_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    accounts.reset_password(account_id, actor=account)
    return {"ok": True, "message": "A temporary password was emailed to the user."}


@router.post("/accounts/{account_id}/active")
def set_active(account_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    accounts.set_active(account_id, bool(payload.get("active")), actor=account)
    return {"ok": True}


# ---- talent, performance, intelligence --------------------------------------------------

@router.get("/talent/skills")
def skill_map(account: dict = Depends(auth.require_hr)) -> dict:
    return talent.skill_map()


@router.post("/talent/search")
def talent_search(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    required = payload.get("required") or []
    if isinstance(required, str):
        required = [s.strip() for s in required.split(",")]
    if payload.get("role_key"):
        from ..roles import get_role

        role = get_role(payload["role_key"])
        required = list(role.skills) if role else required
    nice = payload.get("nice_to_have") or []
    if isinstance(nice, str):
        nice = [s.strip() for s in nice.split(",")]
    return talent.search(required, nice_to_have=nice)


@router.get("/performance/due")
def due(account: dict = Depends(auth.require_hr)) -> dict:
    return {"due": performance.due_reviews()}


@router.get("/performance/intelligence")
def intelligence(role: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    return performance.recruitment_intelligence(role)


@router.get("/audit")
def audit_log(account: dict = Depends(auth.require_hr)) -> dict:
    return {"events": db.fetch_all("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300")}


@router.get("/notifications")
def hr_notifications(account: dict = Depends(auth.require_hr)) -> dict:
    return {"notifications": db.fetch_all("SELECT * FROM notifications WHERE account_id = ? ORDER BY id DESC LIMIT 50", (account["id"],)),
            "unread": int((db.fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE account_id = ? AND is_read = 0", (account["id"],)) or {}).get("n", 0))}


@router.post("/notifications/read")
def hr_notifications_read(account: dict = Depends(auth.require_hr)) -> dict:
    db.execute("UPDATE notifications SET is_read = 1 WHERE account_id = ?", (account["id"],))
    return {"ok": True}
