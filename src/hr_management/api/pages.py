"""HTML pages. Each page is a static template; its script loads data from /api.

/                 landing: careers, employee & HR sign-in
/careers/login    candidate sign-in (email code)      /careers   candidate portal (apply, tests, onboarding)
/login            employee & HR sign-in (user ID)      /password  set a new password (first sign-in)
/hr               HR portal                            /me        employee portal
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__, auth, i18n, pipeline
from ..notifications import format_score
from ..settings import get_settings

router = APIRouter(include_in_schema=False)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _page(name: str, request: Request, session: dict | None = None) -> HTMLResponse:
    marks = pipeline.thresholds()
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in {"COMPANY": get_settings().company_name, "ATS": format_score(marks["ats"]), "TEST": format_score(marks["test"]),
                       "INTERVIEW": format_score(marks["interview"]), "VERSION": __version__, "LANG_PICKER": i18n.picker_html()}.items():
        html = html.replace("{{" + key + "}}", value)
    lang = i18n.request_lang(request, session)
    return HTMLResponse(i18n.localize_html(html, lang, __version__),
                        headers={"Cache-Control": "no-store", "Content-Language": lang, "Vary": "Cookie, Accept-Language"})


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@router.get("/")
def landing(request: Request, session: dict | None = Depends(auth.optional_session)):
    # The landing page is the door chooser (Careers / Employee / HR). It is shown to everyone so
    # a signed-in HR user can still reach the employee sign-in on the same browser.
    return _page("index.html", request, session)


@router.get("/careers/login")
def careers_login(request: Request, session: dict | None = Depends(auth.optional_session)):
    if auth.session_candidate(session):
        return _redirect("/careers")
    return _page("careers_login.html", request, session)


@router.get("/careers")
def careers(request: Request, session: dict | None = Depends(auth.optional_session)):
    if not auth.session_candidate(session):
        return _redirect("/careers/login")
    return _page("careers.html", request, session)


@router.get("/login")
def staff_login(request: Request, session: dict | None = Depends(auth.optional_session)):
    # Always show the form, even when someone is already signed in on this browser: an HR user
    # who opens the employee sign-in (or an emailed link) must be able to sign in as someone else.
    # auth.js shows a "signed in as … / continue" notice when a session exists.
    return _page("login.html", request, session)


@router.get("/password")
def password(request: Request, session: dict | None = Depends(auth.optional_session)):
    if not auth.session_account(session):
        return _redirect("/login")
    return _page("password.html", request, session)


@router.get("/hr")
def hr_portal(request: Request, session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if not account:
        return _redirect("/login")
    if account["must_change_password"]:
        return _redirect("/password")
    if not auth.is_hr(account):
        return _redirect("/me")
    return _page("hr.html", request, session)


@router.get("/me")
def employee_portal(request: Request, session: dict | None = Depends(auth.optional_session)):
    account = auth.session_account(session)
    if not account:
        return _redirect("/login")
    if account["must_change_password"]:
        return _redirect("/password")
    if not account.get("employee_id"):
        return _redirect("/hr")
    return _page("me.html", request, session)
