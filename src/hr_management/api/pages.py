"""HTML pages. Each page is a static template; its script loads data from /api.

/                 landing: careers, employee & HR sign-in
/careers/login    candidate sign-in (email code)      /careers   candidate portal (apply, tests, onboarding)
/login            employee & HR sign-in (user ID)      /password  set a new password (first sign-in)
/hr               HR portal                            /me        employee portal
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__, auth, pipeline
from ..notifications import format_score
from ..settings import get_settings

router = APIRouter(include_in_schema=False)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _page(name: str) -> HTMLResponse:
    marks = pipeline.thresholds()
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in {"COMPANY": get_settings().company_name, "ATS": format_score(marks["ats"]), "TEST": format_score(marks["test"]),
                       "INTERVIEW": format_score(marks["interview"]), "VERSION": __version__}.items():
        html = html.replace("{{" + key + "}}", value)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@router.get("/")
def landing(session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if account:
        return _redirect(auth.home_for(account))
    return _page("index.html")


@router.get("/careers/login")
def careers_login(session: dict | None = Depends(auth.optional_session)):
    if auth.session_candidate(session):
        return _redirect("/careers")
    return _page("careers_login.html")


@router.get("/careers")
def careers(session: dict | None = Depends(auth.optional_session)):
    if not auth.session_candidate(session):
        return _redirect("/careers/login")
    return _page("careers.html")


@router.get("/login")
def staff_login(session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if account:
        return _redirect(auth.home_for(account))
    return _page("login.html")


@router.get("/password")
def password(session: dict | None = Depends(auth.optional_session)):
    if not auth.session_account(session):
        return _redirect("/login")
    return _page("password.html")


@router.get("/hr")
def hr_portal(session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if not account:
        return _redirect("/login")
    if account["must_change_password"]:
        return _redirect("/password")
    if not auth.is_hr(account):
        return _redirect("/me")
    return _page("hr.html")


@router.get("/me")
def employee_portal(session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if not account:
        return _redirect("/login")
    if account["must_change_password"]:
        return _redirect("/password")
    if not account.get("employee_id"):
        return _redirect("/hr")
    return _page("me.html")
