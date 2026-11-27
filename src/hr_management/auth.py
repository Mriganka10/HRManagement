"""Authentication for the three kinds of portal users.

Candidates   -> email + one-time code (no account needed to apply)
Employees    -> user ID (e.g. KZE1001) + password
HR / Admin   -> user ID (e.g. KZH1001) + password

Sessions are a signed, HTTP-only cookie: ``base64(payload).hmac``. Staff sessions carry the
account's ``session_version``; bumping it (password change/reset, deactivation) signs the
account out everywhere. Passwords are hashed with scrypt (stdlib, memory-hard).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import time
from datetime import timedelta
from typing import Any

from fastapi import Cookie, HTTPException, Request, Response

from . import db
from .settings import get_settings

SESSION_COOKIE = "hrm_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HR_ROLES = {"hr_admin", "hr"}
STAFF_ROLES = HR_ROLES | {"employee"}


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 254


# ---- passwords ---------------------------------------------------------------------------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), dklen=32, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def temporary_password() -> str:
    """12 readable characters with upper, lower and digits (no 0/O/1/l confusion)."""
    alphabet = "".join(ch for ch in string.ascii_letters + string.digits if ch not in "0O1lI")
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in value) and any(c.islower() for c in value) and any(c.isupper() for c in value):
            return value


def password_problem(password: str, *, user_id: str = "", email: str = "") -> str:
    cfg = get_settings()
    if len(password) < cfg.password_min_length:
        return f"Use at least {cfg.password_min_length} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Use both letters and numbers."
    lowered = password.lower()
    if user_id and user_id.lower() in lowered or email and email.split("@")[0].lower() in lowered:
        return "Your password must not contain your user ID or email."
    if lowered in {"password123", "kairoz12345", "qwerty12345", "welcome12345"}:
        return "That password is too common."
    return ""


# ---- candidate one-time codes -----------------------------------------------------------

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


# ---- session cookie ---------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload_b64: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def make_session(payload: dict[str, Any]) -> str:
    body = _b64(json.dumps({**payload, "iat": int(time.time())}, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def read_session(cookie: str | None) -> dict[str, Any] | None:
    if not cookie or "." not in cookie:
        return None
    body, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(time.time()) - int(payload.get("iat", 0)) > get_settings().session_max_age_seconds:
        return None
    return payload


def set_session_cookie(response: Response, payload: dict[str, Any]) -> None:
    cfg = get_settings()
    response.set_cookie(SESSION_COOKIE, make_session(payload), max_age=cfg.session_max_age_seconds,
                        httponly=True, samesite="lax", secure=cfg.cookie_secure, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def candidate_session(email: str) -> dict[str, Any]:
    return {"k": "candidate", "sub": db.normalize_email(email)}


def staff_session(account: dict) -> dict[str, Any]:
    return {"k": "staff", "sub": int(account["id"]), "v": int(account["session_version"])}


# ---- resolving the current user -----------------------------------------------------------

def session_candidate(payload: dict | None) -> str | None:
    if not payload or payload.get("k") != "candidate":
        return None
    email = db.normalize_email(str(payload.get("sub") or ""))
    return email if valid_email(email) else None


def session_account(payload: dict | None) -> dict | None:
    if not payload or payload.get("k") != "staff":
        return None
    account = db.fetch_one("SELECT * FROM accounts WHERE id = ?", (int(payload.get("sub") or 0),))
    if not account or not account["is_active"] or int(account["session_version"]) != int(payload.get("v") or -1):
        return None
    return account


def is_hr(account: dict | None) -> bool:
    return bool(account) and account["role"] in HR_ROLES


def home_for(account: dict) -> str:
    if account["must_change_password"]:
        return "/password"
    return "/hr" if is_hr(account) else "/me"


# ---- FastAPI dependencies -----------------------------------------------------------------

def optional_session(hrm_session: str | None = Cookie(default=None)) -> dict | None:
    return read_session(hrm_session)


def require_candidate(hrm_session: str | None = Cookie(default=None)) -> str:
    email = session_candidate(read_session(hrm_session))
    if not email:
        raise HTTPException(status_code=401, detail="Please sign in to the careers portal.")
    return email


def _staff(hrm_session: str | None, *, allow_password_change: bool = False) -> dict:
    account = session_account(read_session(hrm_session))
    if not account:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if account["must_change_password"] and not allow_password_change:
        raise HTTPException(status_code=403, detail="Set a new password before continuing.")
    return account


def require_staff_any(hrm_session: str | None = Cookie(default=None)) -> dict:
    """Signed-in staff, even if they still have to change their temporary password."""
    return _staff(hrm_session, allow_password_change=True)


def require_staff(hrm_session: str | None = Cookie(default=None)) -> dict:
    return _staff(hrm_session)


def require_hr(hrm_session: str | None = Cookie(default=None)) -> dict:
    account = _staff(hrm_session)
    if not is_hr(account):
        raise HTTPException(status_code=403, detail="HR access only.")
    return account


def require_hr_admin(hrm_session: str | None = Cookie(default=None)) -> dict:
    account = _staff(hrm_session)
    if account["role"] != "hr_admin":
        raise HTTPException(status_code=403, detail="HR administrator access only.")
    return account


def require_employee(hrm_session: str | None = Cookie(default=None)) -> dict:
    """An account linked to an employee record (employees, and HR staff who are employees)."""
    account = _staff(hrm_session)
    if not account.get("employee_id"):
        raise HTTPException(status_code=403, detail="This account has no employee profile.")
    return account


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    # Behind the AWS ALB the last hop is the client address the ALB saw.
    return forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")
