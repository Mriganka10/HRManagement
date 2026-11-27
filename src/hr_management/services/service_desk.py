"""HR service desk: tickets, reimbursements, document requests, attendance corrections,
exit requests — one queue with a reference number (REQ-2026-0001), comments and status.

Kinds and what resolving them does:
- ``ticket``                 general HR question/issue
- ``reimbursement``          amount + optional receipt upload; approve/reject
- ``document``               employment certificate / salary certificate → generated on resolve
- ``attendance_correction``  date + times; approving writes the attendance record
- ``exit``                   resignation with last working day; approving sets employee to notice
"""
from __future__ import annotations

from datetime import date

from .. import db, notifications, storage
from ..settings import get_settings
from . import ServiceError

KINDS = {
    "ticket": "HR ticket",
    "reimbursement": "Reimbursement",
    "document": "Document request",
    "attendance_correction": "Attendance correction",
    "exit": "Resignation / exit",
}
TICKET_CATEGORIES = ["Payroll", "Leave & attendance", "IT & access", "Benefits & insurance", "Policy question", "Other"]
REIMBURSEMENT_CATEGORIES = ["Travel", "Internet & phone", "Meals", "Training & certification", "Medical", "Other"]
DOCUMENT_TYPES = ["Employment certificate", "Salary certificate", "Address proof letter", "Experience letter"]
STATUSES = ("open", "in_progress", "approved", "resolved", "rejected", "cancelled")


def _next_ref() -> str:
    year = date.today().year
    row = db.fetch_one("SELECT COUNT(*) AS n FROM service_requests WHERE ref LIKE ?", (f"REQ-{year}-%",))
    return f"REQ-{year}-{int(row['n']) + 1:04d}"


def create(employee: dict, *, kind: str, subject: str, description: str = "", category: str = "",
           amount: float | None = None, payload: dict | None = None, attachment: tuple[str, bytes] | None = None) -> dict:
    if kind not in KINDS:
        raise ServiceError("Unknown request type.")
    payload = payload or {}
    subject = (subject or "").strip()[:200]
    if kind == "reimbursement":
        if not amount or float(amount) <= 0 or float(amount) > 500000:
            raise ServiceError("Enter an amount between ₹1 and ₹5,00,000.")
        subject = subject or f"{category or 'Expense'} reimbursement"
    if kind == "document":
        doc = payload.get("document_type") or category
        if doc not in DOCUMENT_TYPES:
            raise ServiceError("Choose a document type.")
        subject = subject or doc
        payload["document_type"] = doc
    if kind == "attendance_correction":
        try:
            day = date.fromisoformat(str(payload.get("date") or ""))
        except ValueError as exc:
            raise ServiceError("Choose the date to correct.") from exc
        if day > date.today():
            raise ServiceError("You can only correct past dates.")
        if not payload.get("check_in"):
            raise ServiceError("Enter the check-in time.")
        subject = subject or f"Attendance correction for {day.isoformat()}"
    if kind == "exit":
        try:
            last_day = date.fromisoformat(str(payload.get("last_working_day") or ""))
        except ValueError as exc:
            raise ServiceError("Choose your proposed last working day.") from exc
        if last_day <= date.today():
            raise ServiceError("The last working day must be in the future.")
        subject = subject or "Resignation"
    if not subject:
        raise ServiceError("Add a short subject.")
    attachment_key = ""
    if attachment:
        name, data = attachment
        if len(data) > get_settings().max_upload_mb * 1024 * 1024:
            raise ServiceError(f"Attachments must be {get_settings().max_upload_mb} MB or smaller.")
        if not name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            raise ServiceError("Attach a PDF, PNG or JPG.")
        attachment_key = storage.put(storage.new_key(f"requests/{employee['employee_code']}", name), data)
    stamp = db.now_iso()
    for _ in range(3):
        try:
            request_id = db.insert("service_requests", {
                "ref": _next_ref(), "employee_id": employee["id"], "kind": kind, "category": (category or "")[:60],
                "subject": subject, "description": (description or "").strip()[:4000],
                "amount": float(amount) if amount else None, "payload": payload, "attachment_key": attachment_key,
                "status": "open", "created_at": stamp, "updated_at": stamp,
            })
            break
        except Exception:  # ref race: try the next number
            continue
    else:
        raise ServiceError("Could not create the request. Try again.", 503)
    request = get(request_id)
    notifications.notify_hr(f"New {KINDS[kind].lower()}: {request['ref']}", f"{employee['full_name']}: {subject}", f"/hr#/requests/{request_id}")
    db.audit(employee["employee_code"], "request_created", "service_request", request_id, {"kind": kind})
    return request


def get(request_id: int) -> dict:
    row = db.fetch_one(
        """SELECT r.*, e.full_name AS employee_name, e.employee_code, e.department, e.account_id
           FROM service_requests r JOIN employees e ON e.id = r.employee_id WHERE r.id = ?""", (request_id,))
    if not row:
        raise ServiceError("Request not found.", 404)
    row["kind_label"] = KINDS.get(row["kind"], row["kind"])
    row["comments"] = db.fetch_all("SELECT * FROM request_comments WHERE request_id = ? ORDER BY id", (request_id,))
    return row


def list_for(*, employee_id: int | None = None, status: str = "", kind: str = "", limit: int = 300) -> list[dict]:
    where, params = [], []
    if employee_id:
        where.append("r.employee_id = ?"); params.append(employee_id)
    if status == "active":
        where.append("r.status IN ('open', 'in_progress')")
    elif status:
        where.append("r.status = ?"); params.append(status)
    if kind:
        where.append("r.kind = ?"); params.append(kind)
    sql = """SELECT r.id, r.ref, r.kind, r.category, r.subject, r.amount, r.status, r.created_at, r.updated_at,
                    e.full_name AS employee_name, e.employee_code, e.department
             FROM service_requests r JOIN employees e ON e.id = r.employee_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = db.fetch_all(sql + " ORDER BY r.id DESC LIMIT ?", (*params, limit))
    for row in rows:
        row["kind_label"] = KINDS.get(row["kind"], row["kind"])
    return rows


def comment(request_id: int, *, author: str, author_role: str, body: str) -> dict:
    body = (body or "").strip()[:2000]
    if not body:
        raise ServiceError("Write a comment first.")
    request = get(request_id)
    db.insert("request_comments", {"request_id": request_id, "author": author, "author_role": author_role, "body": body,
                                   "created_at": db.now_iso()})
    db.update("service_requests", request_id, {"updated_at": db.now_iso()})
    if author_role == "hr":
        notifications.notify(request["account_id"], f"HR replied on {request['ref']}", body[:140], "/me#/requests")
    else:
        notifications.notify_hr(f"Employee replied on {request['ref']}", body[:140], f"/hr#/requests/{request_id}")
    return get(request_id)


def resolve(request_id: int, *, status: str, resolution: str, actor: dict) -> dict:
    """HR moves a request to in_progress/approved/resolved/rejected; side effects run on approval."""
    from . import attendance, documents

    if status not in {"in_progress", "approved", "resolved", "rejected"}:
        raise ServiceError("Unknown status.")
    request = get(request_id)
    if request["status"] in {"resolved", "rejected", "approved", "cancelled"}:
        raise ServiceError("This request is already closed.", 409)
    if request["kind"] in {"ticket", "document"} and status == "approved":
        status = "resolved"
    if status in {"approved", "resolved"}:
        if request["kind"] == "attendance_correction":
            attendance.apply_correction(request["employee_id"], request.get("payload") or {}, actor=actor["user_id"])
        elif request["kind"] == "document":
            doc = documents.generate(request["employee_id"], (request.get("payload") or {}).get("document_type", "Employment certificate"),
                                     actor=actor["user_id"])
            resolution = (resolution + "\n" if resolution else "") + f"Your document '{doc['title']}' is ready in My documents."
        elif request["kind"] == "exit":
            last_day = (request.get("payload") or {}).get("last_working_day")
            db.update("employees", request["employee_id"], {"status": "notice", "exit_date": last_day, "updated_at": db.now_iso()})
    closed = status in {"approved", "resolved", "rejected"}
    db.update("service_requests", request_id, {
        "status": status, "resolution": (resolution or "").strip()[:2000], "handled_by": actor["user_id"],
        "updated_at": db.now_iso(), "resolved_at": db.now_iso() if closed else None,
    })
    updated = get(request_id)
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (request["employee_id"],))
    label = status.replace("_", " ")
    notifications.notify(employee.get("account_id"), f"{request['ref']} is {label}", resolution[:140], "/me#/requests")
    if closed:
        notifications.send_template("request_update", employee["email"], name=employee["full_name"].split(" ")[0], ref=request["ref"],
                                    subject=request["subject"], status=label, resolution=resolution or "No further action is needed.")
    db.audit(actor["user_id"], f"request_{status}", "service_request", request_id)
    return updated


def cancel(request_id: int, employee: dict) -> dict:
    request = get(request_id)
    if request["employee_id"] != employee["id"]:
        raise ServiceError("Request not found.", 404)
    if not db.update("service_requests", request_id, {"status": "cancelled", "updated_at": db.now_iso()}, where="status = 'open'"):
        raise ServiceError("Only open requests can be cancelled.", 409)
    return get(request_id)
