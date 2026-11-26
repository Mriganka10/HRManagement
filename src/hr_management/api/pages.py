"""HTML pages. Each page is a static template; data is loaded by its script from /api."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import auth, pipeline
from ..notifications import format_score
from ..settings import get_settings

router = APIRouter(include_in_schema=False)
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _page(name: str) -> HTMLResponse:
    marks = pipeline.thresholds()
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in {"COMPANY": get_settings().company_name, "ATS": format_score(marks["ats"]),
                       "TEST": format_score(marks["test"]), "INTERVIEW": format_score(marks["interview"])}.items():
        html = html.replace("{{" + key + "}}", value)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/")
def home(email: str | None = Depends(auth.optional_user)):
    if not email:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/hr" if auth.is_hr(email) else "/app", status_code=303)


@router.get("/login")
def login(email: str | None = Depends(auth.optional_user)):
    if email:
        return RedirectResponse("/hr" if auth.is_hr(email) else "/app", status_code=303)
    return _page("login.html")


@router.get("/app")
def candidate_app(email: str | None = Depends(auth.optional_user)):
    if not email:
        return RedirectResponse("/login", status_code=303)
    return _page("app.html")


@router.get("/hr")
def hr_board(email: str | None = Depends(auth.optional_user)):
    if not email:
        return RedirectResponse("/login", status_code=303)
    if not auth.is_hr(email):
        return RedirectResponse("/app", status_code=303)
    return _page("hr.html")
