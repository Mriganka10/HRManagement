"""Staff accounts: unique user IDs, password login with lockout, password change/reset.

User ID formats (unique, never reused):
- employees: ``KZE1001``, ``KZE1002`` … (also their Employee ID)
- HR staff:  ``KZH1001``, ``KZH1002`` …
"""
from __future__ import annotations

from datetime import timedelta

from .. import auth, db, notifications
from ..settings import get_settings
from . import ServiceError

PREFIX = {"employee": "KZE", "hr": "KZH", "hr_admin": "KZH"}


def next_user_id(role: str) -> str:
    prefix = PREFIX[role]
    rows = db.fetch_all("SELECT user_id FROM accounts WHERE user_id LIKE ?", (f"{prefix}%",))
    rows += db.fetch_all("SELECT employee_code AS user_id FROM employees WHERE employee_code LIKE ?", (f"{prefix}%",))
    numbers = [int(r["user_id"][len(prefix):]) for r in rows if r["user_id"][len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=1000) + 1}"


def create_account(*, email: str, full_name: str, role: str, employee_id: int | None = None,
                   user_id: str = "", password: str = "") -> tuple[dict, str]:
    """Create an account. Returns (account, temporary_password). Retries if a user ID races."""
    if role not in auth.STAFF_ROLES:
        raise ServiceError("Unknown role.")
    email = db.normalize_email(email)
    if db.fetch_one("SELECT id FROM accounts WHERE email = ?", (email,)):
        raise ServiceError("An account with this email already exists.", 409)
    temporary = password or auth.temporary_password()
    for _ in range(5):
        candidate_id = user_id or next_user_id(role)
        stamp = db.now_iso()
        try:
            account_id = db.insert("accounts", {
                "user_id": candidate_id, "email": email, "full_name": full_name.strip(), "role": role,
                "password_hash": auth.hash_password(temporary), "must_change_password": 1, "is_active": 1,
                "session_version": 1, "employee_id": employee_id, "created_at": stamp, "updated_at": stamp,
            })
            return db.fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,)), temporary  # type: ignore[return-value]
        except Exception:  # unique user_id clash from a parallel request: take the next number
            if user_id:
                raise ServiceError("That user ID is already taken.", 409)
    raise ServiceError("Could not allocate a user ID. Try again.", 503)


def login(user_id: str, password: str) -> dict:
    cfg = get_settings()
    user_id = (user_id or "").strip().upper()
    account = db.fetch_one("SELECT * FROM accounts WHERE UPPER(user_id) = ?", (user_id,))
    generic = ServiceError("User ID or password is incorrect.", 401)
    if not account:
        auth.verify_password(password, auth.hash_password("timing-equaliser"))  # same cost as a real check
        raise generic
    locked_until = db.parse_time(account.get("locked_until"))
    if locked_until and locked_until > db.utcnow():
        minutes = max(1, int((locked_until - db.utcnow()).total_seconds() // 60) + 1)
        raise ServiceError(f"Too many failed attempts. Try again in {minutes} minute(s) or ask HR to reset your password.", 423)
    password = password or ""
    matched = auth.verify_password(password, account["password_hash"])
    if not matched and password != password.strip():
        # Copying the temporary password out of an email often brings a trailing space or newline.
        matched = auth.verify_password(password.strip(), account["password_hash"])
    if not matched:
        failures = int(account["failed_logins"]) + 1
        fields = {"failed_logins": failures}
        if failures >= cfg.login_max_failures:
            fields = {"failed_logins": 0, "locked_until": (db.utcnow() + timedelta(minutes=cfg.login_lock_minutes)).isoformat()}
            db.audit(account["user_id"], "account_locked", "account", account["id"])
        db.update("accounts", account["id"], fields)
        raise generic
    if not account["is_active"]:
        raise ServiceError("This account is deactivated. Contact HR.", 403)
    db.update("accounts", account["id"], {"failed_logins": 0, "locked_until": None, "last_login_at": db.now_iso()})
    db.audit(account["user_id"], "login", "account", account["id"])
    return db.fetch_one("SELECT * FROM accounts WHERE id = ?", (account["id"],))  # type: ignore[return-value]


def change_password(account: dict, current: str, new: str) -> dict:
    if not auth.verify_password(current or "", account["password_hash"]):
        raise ServiceError("Your current password is incorrect.", 400)
    problem = auth.password_problem(new or "", user_id=account["user_id"], email=account["email"])
    if problem:
        raise ServiceError(problem)
    if auth.verify_password(new, account["password_hash"]):
        raise ServiceError("Choose a password different from the current one.")
    db.update("accounts", account["id"], {
        "password_hash": auth.hash_password(new), "must_change_password": 0,
        "session_version": int(account["session_version"]) + 1, "updated_at": db.now_iso(),
    })
    db.audit(account["user_id"], "password_changed", "account", account["id"])
    return db.fetch_one("SELECT * FROM accounts WHERE id = ?", (account["id"],))  # type: ignore[return-value]


def reset_password(target_id: int, *, actor: dict) -> str:
    target = db.fetch_one("SELECT * FROM accounts WHERE id = ?", (target_id,))
    if not target:
        raise ServiceError("Account not found.", 404)
    if target["role"] == "hr_admin" and actor["role"] != "hr_admin":
        raise ServiceError("Only an HR administrator can reset another administrator.", 403)
    temporary = auth.temporary_password()
    db.update("accounts", target_id, {
        "password_hash": auth.hash_password(temporary), "must_change_password": 1, "failed_logins": 0,
        "locked_until": None, "session_version": int(target["session_version"]) + 1, "updated_at": db.now_iso(),
    })
    db.audit(actor["user_id"], "password_reset", "account", target_id, {"target": target["user_id"]})
    notifications.send_template("password_reset", target["email"], name=target["full_name"].split(" ")[0],
                                user_id=target["user_id"], password=temporary)
    return temporary


def set_active(target_id: int, active: bool, *, actor: dict) -> None:
    target = db.fetch_one("SELECT * FROM accounts WHERE id = ?", (target_id,))
    if not target:
        raise ServiceError("Account not found.", 404)
    if target["id"] == actor["id"]:
        raise ServiceError("You cannot deactivate your own account.")
    db.update("accounts", target_id, {"is_active": int(active), "session_version": int(target["session_version"]) + 1,
                                      "updated_at": db.now_iso()})
    db.audit(actor["user_id"], "account_activated" if active else "account_deactivated", "account", target_id)


def public(account: dict) -> dict:
    return {key: account.get(key) for key in ("id", "user_id", "email", "full_name", "role", "employee_id",
                                              "must_change_password", "is_active", "last_login_at", "lang")}


def bootstrap_hr_admin() -> None:
    """Create the first HR administrator from HRM_BOOTSTRAP_HR_* settings (once, when no HR exists)."""
    cfg = get_settings()
    if not cfg.bootstrap_hr_email or db.fetch_one("SELECT id FROM accounts WHERE role = 'hr_admin'"):
        return
    if cfg.is_production and not cfg.bootstrap_hr_password:
        return  # never invent a password nobody can see in production; use the CLI instead
    account, password = create_account(email=cfg.bootstrap_hr_email, full_name=cfg.bootstrap_hr_name, role="hr_admin",
                                       password=cfg.bootstrap_hr_password)
    print(f"\n  First HR administrator created → user ID {account['user_id']}"
          f"{'' if cfg.bootstrap_hr_password else f', temporary password {password}'} (must be changed at first sign-in)\n", flush=True)
