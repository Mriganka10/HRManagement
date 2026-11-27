"""HR → Recruitment: pipeline board, candidate detail (scorecard, SWOT), HR decisions,
job openings, benchmarking, onboarding tracker, resume download, email log."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response

from .. import auth, db, pipeline, roles, storage
from ..services import ServiceError, evaluation, onboarding, views

router = APIRouter(prefix="/api/hr/recruitment", tags=["hr-recruitment"])


@router.get("/overview")
def overview(role: str = "", account: dict = Depends(auth.require_hr)) -> dict:
    apps = db.all_applications(limit=2000)
    if role:
        apps = [app for app in apps if app["role_key"] == role]
    return {
        "applications": [views.hr_row(app) for app in apps],
        "stages": [pipeline.stage_view(key) for key in pipeline.STAGES],
        "roles": [{"key": r.key, "title": r.title} for r in roles.all_roles(include_closed=True)],
        "thresholds": pipeline.thresholds(),
    }


@router.get("/applications/{application_id}")
def detail(application_id: int, account: dict = Depends(auth.require_hr)) -> dict:
    app = db.application(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    return {"application": views.hr_detail(app)}


@router.post("/applications/{application_id}/decision")
def decision(application_id: int, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    app = onboarding.hr_decide(application_id, select=bool(payload.get("select")), actor=account, note=str(payload.get("note") or ""))
    return {"application": views.hr_detail(app)}


@router.get("/applications/{application_id}/resume")
def resume(application_id: int, account: dict = Depends(auth.require_hr)) -> Response:
    app = db.application(application_id)
    if not app or not app.get("resume_path"):
        raise HTTPException(status_code=404, detail="Resume not found.")
    try:
        data = storage.get(app["resume_path"])
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found.") from exc
    name = (app["resume_name"] or "resume").replace('"', "")
    return Response(data, media_type=storage.content_type(name), headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/benchmark/{role_key}")
def benchmark(role_key: str, account: dict = Depends(auth.require_hr)) -> dict:
    return evaluation.benchmark(role_key)


@router.get("/onboarding")
def onboarding_tracker(account: dict = Depends(auth.require_hr)) -> dict:
    rows = db.fetch_all(
        """SELECT o.id, o.status, o.submitted_at, o.created_at, a.id AS application_id, a.full_name, a.email, a.role_title,
                  e.employee_code, e.date_of_joining, e.id AS employee_id
           FROM onboarding o JOIN applications a ON a.id = o.application_id LEFT JOIN employees e ON e.id = o.employee_id
           ORDER BY o.id DESC""")
    return {"onboarding": rows}


@router.get("/emails")
def email_log(account: dict = Depends(auth.require_hr)) -> dict:
    return {"emails": [e for e in db.emails(limit=300) if e["kind"] != "otp"]}


# ---- job openings ------------------------------------------------------------------------

@router.get("/openings")
def openings(account: dict = Depends(auth.require_hr)) -> dict:
    rows = []
    for role in roles.all_roles(include_closed=True):
        counts = db.fetch_one("SELECT COUNT(*) AS n, SUM(CASE WHEN stage = 'hired' THEN 1 ELSE 0 END) AS hired FROM applications WHERE role_key = ?", (role.key,))
        rows.append({**role.public(), "annual_ctc": role.annual_ctc, "applicants": int(counts["n"] or 0), "hired": int(counts["hired"] or 0)})
    return {"openings": rows}


def _opening_fields(payload: dict) -> dict:
    title = str(payload.get("title") or "").strip()
    skills = payload.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]
    skills = [s for s in (str(x).strip()[:60] for x in skills) if s][:20]
    if len(title) < 3 or not skills:
        raise ServiceError("A title and at least one required skill are needed.")
    try:
        min_years = max(0.0, float(payload.get("min_years") or 0))
        ctc = max(0.0, float(payload.get("annual_ctc") or 0))
        count = max(1, int(payload.get("openings") or 1))
    except (TypeError, ValueError) as exc:
        raise ServiceError("Experience, CTC and openings must be numbers.") from exc
    description = str(payload.get("description") or "").strip()
    if not description or "Required skills:" not in description:
        description = roles.compose_description(str(payload.get("summary") or description or f"Join our team as {title}."),
                                                str(payload.get("responsibilities") or ""), skills, min_years)
    return {"title": title, "department": str(payload.get("department") or "").strip(), "location": str(payload.get("location") or "").strip(),
            "employment_type": str(payload.get("employment_type") or "Full-time"), "experience": str(payload.get("experience") or f"{min_years:g}+ years"),
            "min_years": min_years, "skills": skills, "description": description[:6000], "openings": count, "annual_ctc": ctc}


@router.post("/openings")
def create_opening(payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    fields = _opening_fields(payload)
    key = roles.slugify(fields["title"])
    if db.fetch_one("SELECT id FROM job_openings WHERE key = ?", (key,)):
        key = f"{key}-{db.utcnow().strftime('%m%d%H%M')}"
    stamp = db.now_iso()
    db.insert("job_openings", {**fields, "key": key, "status": "open", "created_at": stamp, "updated_at": stamp})
    db.audit(account["user_id"], "opening_created", "job_opening", key)
    return {"opening": roles.get_role(key).public()}  # type: ignore[union-attr]


@router.put("/openings/{key}")
def update_opening(key: str, payload: Annotated[dict, Body()], account: dict = Depends(auth.require_hr)) -> dict:
    role = roles.get_role(key)
    if not role:
        raise HTTPException(status_code=404, detail="Opening not found.")
    fields = _opening_fields({**role.public(), "annual_ctc": role.annual_ctc, **payload})
    if payload.get("status") in {"open", "closed"}:
        fields["status"] = payload["status"]
    db.update("job_openings", role.id, {**fields, "updated_at": db.now_iso()})
    db.audit(account["user_id"], "opening_updated", "job_opening", key)
    return {"opening": roles.get_role(key).public()}  # type: ignore[union-attr]
