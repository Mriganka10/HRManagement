"""Candidate endpoints: roles, applications (resume + ATS), mock test and mock interview."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, UploadFile

from .. import auth, db, notifications, pipeline
from ..roles import all_roles
from ..services import Notice, assessment, interview, screening, views

router = APIRouter(prefix="/api", tags=["candidate"])


def queue_email(background: BackgroundTasks, notice: Notice | None) -> None:
    """Emails go out after the response, so a slow mail server never delays the candidate."""
    if notice is None:
        return
    app = db.application(notice.application_id)
    if app:
        background.add_task(
            notifications.send_stage_email, notice.kind, app,
            score=notice.score, threshold=notice.threshold, next_threshold=notice.next_threshold,
        )


def owned_application(application_id: int, email: str) -> dict:
    app = db.application(application_id, email)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    return app


@router.get("/roles")
def roles(email: str = Depends(auth.require_user)) -> dict:
    applied = {app["role_key"] for app in db.applications_for_user(email)}
    return {
        "roles": [{**role.public(), "applied": role.key in applied} for role in all_roles()],
        "thresholds": pipeline.thresholds(),
    }


@router.get("/applications")
def my_applications(background: BackgroundTasks, email: str = Depends(auth.require_user)) -> dict:
    apps = db.applications_for_user(email)
    for app in apps:
        queue_email(background, assessment.finalize_if_expired(app))
    return {"applications": [views.candidate_application(app) for app in db.applications_for_user(email)]}


@router.post("/applications")
async def apply(
    background: BackgroundTasks,
    role_key: Annotated[str, Form()],
    full_name: Annotated[str, Form()],
    experience_years: Annotated[float, Form()] = 0,
    phone: Annotated[str, Form()] = "",
    resume: UploadFile = File(...),
    email: str = Depends(auth.require_user),
) -> dict:
    content = await resume.read()
    app, notice = screening.submit_application(
        email=email, role_key=role_key, full_name=full_name, phone=phone,
        experience_years=experience_years, filename=resume.filename or "", content=content,
    )
    queue_email(background, notice)
    return {"application": views.candidate_application(app)}


@router.get("/applications/{application_id}")
def application_detail(application_id: int, background: BackgroundTasks, email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    queue_email(background, assessment.finalize_if_expired(app))
    return {"application": views.candidate_application(owned_application(application_id, email))}


# ---- mock test ------------------------------------------------------------------------

@router.post("/applications/{application_id}/test/start")
def test_start(application_id: int, background: BackgroundTasks, email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    expired = assessment.finalize_if_expired(app)
    if expired:
        queue_email(background, expired)
        raise HTTPException(status_code=409, detail="Time is up for this test. Your autosaved answers were submitted.")
    return {"test": assessment.start_test(app)}


@router.post("/applications/{application_id}/test/autosave")
def test_autosave(application_id: int, payload: Annotated[dict, Body()], email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    return assessment.autosave(app, payload.get("answers"), payload.get("integrity"))


@router.post("/applications/{application_id}/test/submit")
def test_submit(application_id: int, payload: Annotated[dict, Body()], background: BackgroundTasks,
                email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    _, notice = assessment.submit(app, payload.get("answers"), payload.get("integrity"))
    queue_email(background, notice)
    return {"application": views.candidate_application(owned_application(application_id, email))}


# ---- mock interview -------------------------------------------------------------------

@router.post("/applications/{application_id}/interview/start")
def interview_start(application_id: int, email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    return {"interview": interview.start(app)}


@router.post("/applications/{application_id}/interview/autosave")
def interview_autosave(application_id: int, payload: Annotated[dict, Body()], email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    return interview.autosave(app, payload.get("answers"), payload.get("integrity"))


@router.post("/applications/{application_id}/interview/complete")
def interview_complete(application_id: int, payload: Annotated[dict, Body()], background: BackgroundTasks,
                       email: str = Depends(auth.require_user)) -> dict:
    app = owned_application(application_id, email)
    _, notice = interview.complete(app, payload.get("answers"), payload.get("integrity"))
    queue_email(background, notice)
    return {"application": views.candidate_application(owned_application(application_id, email))}
