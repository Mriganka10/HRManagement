"""Selection → onboarding → employee.

1. When a candidate is selected (automatically after the interview, or by HR), an onboarding
   record is created and **prefilled from the resume** (contact, skills, education,
   experience, certifications) plus the offer details from the job opening.
2. The candidate reviews every field in the careers portal, edits what is wrong, adds the
   remaining details (DOB, address, emergency contact, PAN, bank) and submits.
3. Submission creates the employee record, the employee account (unique user ID = Employee ID),
   the salary structure from the offer CTC, marks the application ``hired`` and emails the
   user ID + temporary password. HR is notified.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .. import db, notifications, pipeline, storage
from ..engines.resume import parse_resume
from ..roles import get_role
from ..settings import get_settings
from . import ServiceError
from .accounts import create_account, next_user_id

PHONE_RE = re.compile(r"(\+?\d[\d\s-]{8,}\d)")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+", re.I)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_RE = re.compile(r"^\d{9,18}$")

TEXT_FIELDS = (
    "full_name", "phone", "date_of_birth", "gender", "blood_group", "address", "linkedin",
    "emergency_contact_name", "emergency_contact_relation", "emergency_contact_phone",
    "pan_number", "bank_account_name", "bank_account_number", "bank_ifsc",
)
LIST_FIELDS = ("skills", "education", "experience", "certifications")


# ---- resume → form -----------------------------------------------------------------------

def _split_line(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*[|•·–—]\s*|\s{2,}", line) if part.strip()]


def parse_education(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        line = line.strip(" -•\t")
        if len(line) < 4:
            continue
        parts = _split_line(line)
        years = re.findall(r"(?:19|20)\d{2}", line)
        score = next((p for p in parts if re.search(r"(cgpa|gpa|%|percent)", p, re.I)), "")
        rows.append({
            "degree": parts[0] if parts else line,
            "institution": parts[1] if len(parts) > 1 else "",
            "year": years[-1] if years else "",
            "score": score,
        })
    return rows[:6]


def parse_experience(text: str) -> list[dict]:
    entries: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[:1] in "-•*–" and entries:
            entries[-1]["highlights"].append(line.lstrip("-•*– ").strip())
            continue
        parts = _split_line(line)
        period = next((p for p in parts if re.search(r"(?:19|20)\d{2}|present|current", p, re.I)), "")
        rest = [p for p in parts if p != period]
        entries.append({"title": rest[0] if rest else line, "company": rest[1] if len(rest) > 1 else "",
                        "period": period, "highlights": []})
    for entry in entries:
        entry["highlights"] = entry["highlights"][:4]
    return entries[:8]


def prefill_from_resume(app: dict) -> dict[str, Any]:
    data: dict[str, Any] = {"full_name": app.get("full_name", ""), "phone": app.get("phone", ""), "skills": [],
                            "education": [], "experience": [], "certifications": [], "linkedin": "", "address": ""}
    key = app.get("resume_path") or ""
    if not key:
        return data
    path = None
    try:
        path = storage.local_copy(key)
        resume = parse_resume(path)
    except Exception:  # noqa: BLE001 - prefill is a convenience; the form still works empty
        return data
    finally:
        if path is not None and not Path(key).is_absolute() and get_settings().storage_backend == "s3":
            path.unlink(missing_ok=True)
    contact = resume.sections.get("contact", "") or resume.text[:600]
    if not data["phone"]:
        match = PHONE_RE.search(contact)
        data["phone"] = match.group(1).strip() if match else ""
    link = LINKEDIN_RE.search(resume.text)
    data["linkedin"] = link.group(0) if link else ""
    for part in _split_line(contact.replace("\n", " | ")):
        if "," in part and not any(ch.isdigit() for ch in part) and "@" not in part and "linkedin" not in part.lower():
            data["address"] = part  # usually "City, Country"
            break
    data["skills"] = list(dict.fromkeys(resume.inferred_skills))[:30]
    data["education"] = parse_education(resume.sections.get("education", ""))
    data["experience"] = parse_experience(resume.sections.get("experience", ""))
    data["certifications"] = [line.strip(" -•") for line in resume.sections.get("certifications", "").splitlines() if line.strip()][:10]
    return data


def _next_monday(days_ahead: int = 14) -> date:
    target = date.today() + timedelta(days=days_ahead)
    return target + timedelta(days=(7 - target.weekday()) % 7)


def offer_details(app: dict) -> dict[str, Any]:
    role = get_role(app["role_key"])
    return {
        "designation": app["role_title"],
        "department": role.department if role else "",
        "work_location": role.location if role else "",
        "employment_type": role.employment_type if role else "Full-time",
        "annual_ctc": role.annual_ctc if role else 0,
        "date_of_joining": _next_monday().isoformat(),
    }


# ---- lifecycle ---------------------------------------------------------------------------

def open_onboarding(application_id: int) -> dict:
    """Create the onboarding record for a selected candidate (idempotent)."""
    existing = db.fetch_one("SELECT * FROM onboarding WHERE application_id = ?", (application_id,))
    if existing:
        return existing
    app = db.application(application_id)
    if not app:
        raise ServiceError("Application not found.", 404)
    prefill = {**prefill_from_resume(app), "offer": offer_details(app)}
    stamp = db.now_iso()
    try:
        db.insert("onboarding", {"application_id": application_id, "email": app["email"], "status": "pending",
                                 "prefill": prefill, "form": {}, "created_at": stamp, "updated_at": stamp})
    except Exception:  # created concurrently
        pass
    db.add_event(application_id, "onboarding_opened", actor="system")
    notifications.notify_hr("Candidate selected", f"{app['full_name']} was selected for {app['role_title']}. Onboarding form sent.", "/hr#/onboarding")
    return db.fetch_one("SELECT * FROM onboarding WHERE application_id = ?", (application_id,))  # type: ignore[return-value]


def hr_decide(application_id: int, *, select: bool, actor: dict, note: str = "") -> dict:
    app = db.application(application_id)
    if not app:
        raise ServiceError("Application not found.", 404)
    target = pipeline.SELECTED if select else pipeline.NOT_SELECTED
    allowed = (pipeline.INTERVIEW_PASSED,) if select else (pipeline.INTERVIEW_PASSED, pipeline.SELECTED)
    if not db.transition_stage(application_id, allowed, target):
        raise ServiceError(f"This candidate is '{pipeline.stage_view(app['stage'])['label']}', so that action is not available.", 409)
    db.add_event(application_id, "hr_selected" if select else "hr_not_selected", actor=actor["user_id"],
                 from_stage=app["stage"], to_stage=target, detail={"note": note[:500]})
    db.audit(actor["user_id"], "candidate_selected" if select else "candidate_not_selected", "application", application_id)
    if select:
        open_onboarding(application_id)
    notifications.send_stage_email(pipeline.STAGE_EMAILS[target], app, score=app.get("interview_score") or 0, threshold=0)
    return db.application(application_id)  # type: ignore[return-value]


def form_for_candidate(app: dict) -> dict:
    record = db.fetch_one("SELECT * FROM onboarding WHERE application_id = ?", (app["id"],))
    if not record:
        if app["stage"] != pipeline.SELECTED:
            raise ServiceError("Onboarding is not open for this application.", 409)
        record = open_onboarding(app["id"])
    prefill = record.get("prefill") or {}
    form = {**{k: v for k, v in prefill.items() if k != "offer"}, **(record.get("form") or {})}
    form["email"] = app["email"]
    return {"status": record["status"], "form": form, "offer": prefill.get("offer", {}),
            "prefilled_fields": [k for k, v in prefill.items() if k != "offer" and v], "submitted_at": record.get("submitted_at")}


def _clean_form(raw: dict) -> dict:
    form: dict[str, Any] = {}
    for key in TEXT_FIELDS:
        form[key] = str(raw.get(key) or "").strip()[:500]
    form["pan_number"] = form["pan_number"].upper().replace(" ", "")
    form["bank_ifsc"] = form["bank_ifsc"].upper().replace(" ", "")
    form["bank_account_number"] = re.sub(r"\s", "", form["bank_account_number"])
    skills = raw.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]
    form["skills"] = [str(s).strip()[:60] for s in skills if str(s).strip()][:40]
    for key, fields in (("education", ("degree", "institution", "year", "score")),
                        ("experience", ("title", "company", "period"))):
        rows = raw.get(key) if isinstance(raw.get(key), list) else []
        cleaned = []
        for row in rows[:10]:
            if not isinstance(row, dict):
                continue
            item = {f: str(row.get(f) or "").strip()[:200] for f in fields}
            if key == "experience":
                item["highlights"] = [str(h).strip()[:300] for h in (row.get("highlights") or []) if str(h).strip()][:6]
            if any(item.get(f) for f in fields):
                cleaned.append(item)
        form[key] = cleaned
    certs = raw.get("certifications") or []
    if isinstance(certs, str):
        certs = certs.splitlines()
    form["certifications"] = [str(c).strip()[:200] for c in certs if str(c).strip()][:15]
    return form


def validate(form: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    for key, label in (("full_name", "Full name"), ("phone", "Phone"), ("date_of_birth", "Date of birth"),
                       ("address", "Current address"), ("emergency_contact_name", "Emergency contact name"),
                       ("emergency_contact_phone", "Emergency contact phone"), ("pan_number", "PAN"),
                       ("bank_account_name", "Account holder name"), ("bank_account_number", "Bank account number"),
                       ("bank_ifsc", "IFSC")):
        if not form.get(key):
            errors[key] = f"{label} is required."
    if form.get("phone") and len(re.sub(r"\D", "", form["phone"])) < 10:
        errors["phone"] = "Enter a valid phone number."
    if form.get("emergency_contact_phone") and len(re.sub(r"\D", "", form["emergency_contact_phone"])) < 10:
        errors["emergency_contact_phone"] = "Enter a valid phone number."
    if form.get("date_of_birth"):
        try:
            dob = date.fromisoformat(form["date_of_birth"])
            age = (date.today() - dob).days / 365.25
            if not 18 <= age <= 70:
                errors["date_of_birth"] = "Age must be between 18 and 70."
        except ValueError:
            errors["date_of_birth"] = "Use the date picker (YYYY-MM-DD)."
    if form.get("pan_number") and not PAN_RE.match(form["pan_number"]):
        errors["pan_number"] = "PAN looks like ABCDE1234F."
    if form.get("bank_ifsc") and not IFSC_RE.match(form["bank_ifsc"]):
        errors["bank_ifsc"] = "IFSC looks like HDFC0001234."
    if form.get("bank_account_number") and not ACCOUNT_RE.match(form["bank_account_number"]):
        errors["bank_account_number"] = "Account number is 9–18 digits."
    if not form.get("skills"):
        errors["skills"] = "Add at least one skill."
    return errors


def save_draft(app: dict, raw: dict) -> dict:
    record = db.fetch_one("SELECT * FROM onboarding WHERE application_id = ?", (app["id"],))
    if not record or record["status"] != "pending":
        raise ServiceError("This onboarding form can no longer be edited.", 409)
    db.update("onboarding", record["id"], {"form": _clean_form(raw), "updated_at": db.now_iso()})
    return {"saved": True}


def submit(app: dict, raw: dict, *, confirmed: bool) -> dict:
    record = db.fetch_one("SELECT * FROM onboarding WHERE application_id = ?", (app["id"],))
    if not record or record["status"] != "pending" or app["stage"] != pipeline.SELECTED:
        raise ServiceError("This onboarding form is not open.", 409)
    if not confirmed:
        raise ServiceError("Please confirm that the details are correct.")
    form = _clean_form(raw)
    errors = validate(form)
    if errors:
        raise ServiceError("Please fix the highlighted fields: " + "; ".join(errors.values()), 422)
    # Claim the record first so a double submit cannot create two employees.
    if not db.update("onboarding", record["id"], {"status": "processing", "form": form, "updated_at": db.now_iso()},
                     where="status = 'pending'"):
        raise ServiceError("This form is already being processed.", 409)
    try:
        employee, account, password = create_employee_from_onboarding(app, form, (record.get("prefill") or {}).get("offer", {}))
    except Exception:
        db.update("onboarding", record["id"], {"status": "pending"})
        raise
    db.update("onboarding", record["id"], {"status": "completed", "employee_id": employee["id"],
                                           "submitted_at": db.now_iso(), "updated_at": db.now_iso()})
    db.transition_stage(app["id"], (pipeline.SELECTED,), pipeline.HIRED)
    db.add_event(app["id"], "hired", actor=app["email"], from_stage=pipeline.SELECTED, to_stage=pipeline.HIRED,
                 detail={"employee_code": employee["employee_code"]})
    notifications.send_template("welcome_credentials", app["email"], application_id=app["id"],
                                name=form["full_name"].split(" ")[0], employee_code=employee["employee_code"],
                                user_id=account["user_id"], password=password)
    notifications.notify_hr("New employee onboarded",
                            f"{employee['full_name']} ({employee['employee_code']}) joins as {employee['designation']} on {employee['date_of_joining']}.",
                            f"/hr#/employees/{employee['id']}")
    return {"employee_code": employee["employee_code"], "user_id": account["user_id"]}


def create_employee_from_onboarding(app: dict, form: dict, offer: dict) -> tuple[dict, dict, str]:
    from . import payroll  # local import: payroll imports people helpers

    cfg = get_settings()
    if db.fetch_one("SELECT id FROM employees WHERE email = ?", (app["email"],)):
        raise ServiceError("An employee with this email already exists. Contact HR.", 409)
    joining = offer.get("date_of_joining") or date.today().isoformat()
    probation_end = (date.fromisoformat(joining) + timedelta(days=30 * cfg.probation_months)).isoformat()
    stamp = db.now_iso()
    code = next_user_id("employee")
    employee_id = db.insert("employees", {
        "employee_code": code, "application_id": app["id"], "full_name": form["full_name"], "email": app["email"],
        "phone": form["phone"], "designation": offer.get("designation", app["role_title"]),
        "department": offer.get("department", ""), "role_key": app["role_key"], "date_of_joining": joining,
        "employment_type": offer.get("employment_type", "Full-time"), "work_location": offer.get("work_location", ""),
        "status": "probation", "probation_end": probation_end, "date_of_birth": form["date_of_birth"],
        "gender": form["gender"], "blood_group": form["blood_group"], "address": form["address"],
        "emergency_contact_name": f"{form['emergency_contact_name']} ({form['emergency_contact_relation']})".replace(" ()", ""),
        "emergency_contact_phone": form["emergency_contact_phone"], "pan_number": form["pan_number"],
        "bank_account_name": form["bank_account_name"], "bank_account_number": form["bank_account_number"],
        "bank_ifsc": form["bank_ifsc"], "linkedin": form["linkedin"], "skills": form["skills"],
        "education": form["education"], "experience": form["experience"], "certifications": form["certifications"],
        "annual_ctc": float(offer.get("annual_ctc") or 0), "created_at": stamp, "updated_at": stamp,
    })
    account, password = create_account(email=app["email"], full_name=form["full_name"], role="employee",
                                       employee_id=employee_id, user_id=code)
    db.update("employees", employee_id, {"account_id": account["id"]})
    if float(offer.get("annual_ctc") or 0) > 0:
        payroll.save_structure(employee_id, float(offer["annual_ctc"]), monthly_tds=0, effective_from=joining, actor="onboarding")
    db.audit("system", "employee_created", "employee", employee_id, {"code": code, "application_id": app["id"]})
    return db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,)), account, password  # type: ignore[return-value]
