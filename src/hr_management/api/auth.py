"""Sign-in endpoints: request an email code, verify it, sign out, who am I."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from .. import auth, db, notifications
from ..engines.guardrails import enforce as enforce_limit
from ..settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
        response["dev_otp"] = code  # local development only (HRM_DEV_RETURN_OTP=false in production)
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
    auth.set_session_cookie(response, email)
    return {"email": email, "is_hr": auth.is_hr(email), "redirect": "/hr" if auth.is_hr(email) else "/app"}


@router.post("/logout")
def logout(response: Response) -> dict:
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(email: str = Depends(auth.require_user)) -> dict:
    return {"email": email, "is_hr": auth.is_hr(email), "company": get_settings().company_name}
