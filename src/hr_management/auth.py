"""Email OTP sign-in and signed session cookies (same model as Job-Hunting-Agent).

- A 6-digit code is emailed; only its HMAC hash is stored, it expires, and wrong
  guesses are capped per code.
- The session cookie is ``base64(payload).hmac`` — HTTP-only, SameSite=Lax, and
  ``Secure`` when HRM_COOKIE_SECURE=true (always in production).
- HR users are the emails listed in HRM_HR_EMAILS.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta

from fastapi import Cookie, HTTPException, Request, Response

from . import db
from .settings import get_settings

SESSION_COOKIE = "hrm_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 254


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{db.normalize_email(email)}:{code.strip()}".encode(), hashlib.sha256).hexdigest()


def issue_otp(email: str) -> str:
    code = new_otp()
    db.save_otp(email, hash_otp(email, code), db.utcnow() + timedelta(minutes=get_settings().otp_ttl_minutes))
    return code


def verify_otp(email: str, code: str) -> str:
    return db.consume_otp(email, hash_otp(email, code), compare=hmac.compare_digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload_b64: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def make_session(email: str) -> str:
    payload = _b64(json.dumps({"email": db.normalize_email(email), "iat": int(time.time())}).encode())
    return f"{payload}.{_sign(payload)}"


def read_session(cookie: str | None) -> str | None:
    if not cookie or "." not in cookie:
        return None
    payload_b64, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload_b64)):
        return None
    try:
        payload = json.loads(_unb64(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(time.time()) - int(payload.get("iat", 0)) > get_settings().session_max_age_seconds:
        return None
    email = db.normalize_email(str(payload.get("email") or ""))
    return email if valid_email(email) else None


def set_session_cookie(response: Response, email: str) -> None:
    cfg = get_settings()
    response.set_cookie(
        SESSION_COOKIE, make_session(email), max_age=cfg.session_max_age_seconds,
        httponly=True, samesite="lax", secure=cfg.cookie_secure, path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def is_hr(email: str | None) -> bool:
    return bool(email) and db.normalize_email(email or "") in get_settings().hr_emails


# ---- FastAPI dependencies -------------------------------------------------------------

def optional_user(hrm_session: str | None = Cookie(default=None)) -> str | None:
    return read_session(hrm_session)


def require_user(hrm_session: str | None = Cookie(default=None)) -> str:
    email = read_session(hrm_session)
    if not email:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return email


def require_hr(hrm_session: str | None = Cookie(default=None)) -> str:
    email = require_user(hrm_session)
    if not is_hr(email):
        raise HTTPException(status_code=403, detail="HR access only.")
    return email


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")
