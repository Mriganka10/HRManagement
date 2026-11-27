"""Sign-in endpoints: candidate email codes, staff user-ID/password, password change, sign-out."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from .. import auth, db, notifications
from ..engines.guardrails import enforce as enforce_limit
from ..services import accounts
from ..settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---- candidates --------------------------------------------------------------------------

@router.post("/request-otp")
def request_otp(request: Request, payload: Annotated[dict, Body()]) -> dict:
    email = db.normalize_email(str(payload.get("email") or ""))
    if not auth.valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    enforce_limit("otp_request_ip", auth.client_ip(request))
    enforce_limit("otp_request_email", email)
    code = auth.issue_otp(email)
    sent = notifications.send(notifications.render("otp", email, code=code))
    cfg = get_settings()
    if not sent and not cfg.dev_return_otp:
        raise HTTPException(status_code=503, detail="We could not send the email right now. Please try again shortly.")
    response = {"sent": True, "email": email, "ttl_minutes": cfg.otp_ttl_minutes}
    if cfg.dev_return_otp:
        response["dev_otp"] = code  # development only; always off when HRM_ENVIRONMENT=production
    return response


@router.post("/verify")
def verify(request: Request, response: Response, payload: Annotated[dict, Body()]) -> dict:
    email = db.normalize_email(str(payload.get("email") or ""))
    code = str(payload.get("otp") or "").strip()
    if not auth.valid_email(email) or not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code from your email.")
    enforce_limit("otp_verify_ip", auth.client_ip(request))
    result = auth.verify_otp(email, code)
    messages = {"invalid": "That code is not correct.", "expired": "That code has expired. Request a new one.",
                "locked": "Too many wrong attempts. Request a new code."}
    if result != "ok":
        raise HTTPException(status_code=400, detail=messages.get(result, "Could not verify the code."))
    db.ensure_user(email)
    db.touch_login(email)
    auth.set_session_cookie(response, auth.candidate_session(email))
    return {"email": email, "redirect": "/careers"}


# ---- employees & HR ----------------------------------------------------------------------

@router.post("/login")
def login(request: Request, response: Response, payload: Annotated[dict, Body()]) -> dict:
    enforce_limit("staff_login_ip", auth.client_ip(request))
    account = accounts.login(str(payload.get("user_id") or ""), str(payload.get("password") or ""))
    auth.set_session_cookie(response, auth.staff_session(account))
    return {"user_id": account["user_id"], "role": account["role"], "must_change_password": bool(account["must_change_password"]),
            "redirect": auth.home_for(account)}


@router.post("/change-password")
def change_password(response: Response, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_staff_any)) -> dict:
    updated = accounts.change_password(account, str(payload.get("current_password") or ""), str(payload.get("new_password") or ""))
    auth.set_session_cookie(response, auth.staff_session(updated))  # new session version → other devices signed out
    return {"ok": True, "redirect": auth.home_for(updated)}


@router.post("/logout")
def logout(response: Response) -> dict:
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(session: dict | None = Depends(auth.optional_session)) -> dict:
    cfg = get_settings()
    candidate = auth.session_candidate(session)
    if candidate:
        return {"kind": "candidate", "email": candidate, "company": cfg.company_name}
    account = auth.session_account(session)
    if not account:
        raise HTTPException(status_code=401, detail="Please sign in.")
    data = {"kind": "staff", "company": cfg.company_name, **accounts.public(account), "is_hr": auth.is_hr(account)}
    if account.get("employee_id"):
        emp = db.fetch_one("SELECT employee_code, designation, department FROM employees WHERE id = ?", (account["employee_id"],))
        data["employee"] = emp
        data["is_manager"] = bool(db.fetch_one("SELECT id FROM employees WHERE manager_id = ? AND status != 'exited' LIMIT 1",
                                               (account["employee_id"],)))
    return data
