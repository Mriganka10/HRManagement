"""HR endpoints: pipeline board, candidate detail, resume download, email log (read-only for now)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import auth, db, pipeline
from ..roles import all_roles
from ..services import views
from ..settings import get_settings

router = APIRouter(prefix="/api/hr", tags=["hr"])


@router.get("/overview")
def overview(role: str = "", hr_email: str = Depends(auth.require_hr)) -> dict:
    apps = db.all_applications()
    if role:
        apps = [app for app in apps if app["role_key"] == role]
    counts: dict[str, int] = {}
    for app in apps:
        counts[app["stage"]] = counts.get(app["stage"], 0) + 1
    return {
        "applications": [views.hr_row(app) for app in apps],
        "counts": counts,
        "stages": [pipeline.stage_view(key) for key in pipeline.STAGES],
        "roles": [{"key": item.key, "title": item.title} for item in all_roles()],
        "thresholds": pipeline.thresholds(),
        "email_backend": get_settings().email_backend,
    }


@router.get("/applications/{application_id}")
def detail(application_id: int, hr_email: str = Depends(auth.require_hr)) -> dict:
    app = db.application(application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    return {"application": views.hr_detail(app)}


@router.get("/applications/{application_id}/resume")
def resume(application_id: int, hr_email: str = Depends(auth.require_hr)) -> FileResponse:
    app = db.application(application_id)
    path = Path(app["resume_path"]) if app else None
    upload_root = get_settings().upload_dir.resolve()
    if not path or not path.is_file() or upload_root not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="Resume not found.")
    return FileResponse(path, filename=app["resume_name"] or path.name)  # type: ignore[index]


@router.get("/emails")
def email_log(hr_email: str = Depends(auth.require_hr)) -> dict:
    return {"emails": db.emails(limit=200)}
