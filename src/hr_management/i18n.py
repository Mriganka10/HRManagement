"""Interface languages: English (default) and Arabic.

How a page gets its language (first match wins):
1. the ``hrm_lang`` cookie, set by the language picker on every page;
2. the language saved on the signed-in account (staff) or candidate profile, so a
   choice follows the person to a new device;
3. the browser's ``Accept-Language`` header;
4. ``HRM_DEFAULT_LANGUAGE`` (``en`` unless changed).

The server only sets ``<html lang dir>`` and loads the translator. Pages are written in
English; ``static/js/i18n.js`` swaps interface text using ``static/js/i18n/<lang>.js``.
Names, job descriptions, resumes, questions, code and anything people type stay as entered.

Emails use the recipient's saved language (see ``notifications.render``) and the employee
assistant answers in the language of the page it is used from.
"""
from __future__ import annotations

import re

from fastapi import Request

from . import db

LANG_COOKIE = "hrm_lang"
# code -> (name shown in the picker, text direction)
LANGUAGES: dict[str, tuple[str, str]] = {"en": ("English", "ltr"), "ar": ("العربية", "rtl")}
ARABIC_FONT = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700"
               "&family=Noto+Naskh+Arabic:wght@500;600&display=swap")


def default_lang() -> str:
    from .settings import get_settings

    return normalize_lang(getattr(get_settings(), "default_language", "en"), fallback="en")


def normalize_lang(value: str | None, fallback: str | None = None) -> str:
    code = str(value or "").strip().lower().replace("_", "-").split("-")[0]
    if code in LANGUAGES:
        return code
    return fallback if fallback is not None else default_lang()


def is_rtl(lang: str) -> bool:
    return LANGUAGES.get(normalize_lang(lang), ("", "ltr"))[1] == "rtl"


def _accept_language(header: str | None) -> str | None:
    for part in (header or "").split(","):
        code = part.split(";")[0].strip().lower().split("-")[0]
        if code in LANGUAGES:
            return code
    return None


def request_lang(request: Request | None, session: dict | None = None) -> str:
    """The language for this request (cookie → saved preference → browser → default)."""
    if request is not None:
        cookie = request.cookies.get(LANG_COOKIE)
        if cookie and normalize_lang(cookie, fallback="") in LANGUAGES:
            return normalize_lang(cookie)
    saved = saved_lang(session)
    if saved:
        return saved
    if request is not None:
        browser = _accept_language(request.headers.get("accept-language"))
        if browser:
            return browser
    return default_lang()


def saved_lang(session: dict | None) -> str | None:
    from . import auth

    if not session:
        return None
    try:
        account = auth.session_account(session)
        if account and account.get("lang"):
            return normalize_lang(account["lang"], fallback="") or None
        email = auth.session_candidate(session)
        if email:
            row = db.fetch_one("SELECT lang FROM users WHERE email = ?", (email,))
            if row and row.get("lang"):
                return normalize_lang(row["lang"], fallback="") or None
    except Exception:  # a language lookup must never break a page
        return None
    return None


def lang_for_email(email: str | None) -> str:
    """The saved language of whoever owns this address (staff account first, then candidate)."""
    address = db.normalize_email(email or "")
    if address:
        try:
            row = db.fetch_one("SELECT lang FROM accounts WHERE LOWER(email) = ? AND lang IS NOT NULL AND lang != '' "
                               "ORDER BY id DESC LIMIT 1", (address,))
            if not row:
                row = db.fetch_one("SELECT lang FROM users WHERE email = ? AND lang IS NOT NULL AND lang != ''", (address,))
            if row:
                return normalize_lang(row["lang"])
        except Exception:
            pass
    return default_lang()


def remember(lang: str, *, account_id: int | None = None, candidate_email: str | None = None) -> None:
    """Save a person's language so emails and new devices use it."""
    code = normalize_lang(lang, fallback="")
    if not code:
        return
    if account_id:
        db.execute("UPDATE accounts SET lang = ? WHERE id = ?", (code, account_id))
    if candidate_email:
        db.execute("UPDATE users SET lang = ? WHERE email = ?", (code, db.normalize_email(candidate_email)))


def picker_html(extra_class: str = "") -> str:
    """The language menu. i18n.js selects the current language and saves a change."""
    options = "".join(f'<option value="{code}" lang="{code}">{name}</option>' for code, (name, _) in LANGUAGES.items())
    return (f'<label class="lang-picker {extra_class}" data-no-i18n><span class="sr-only">Language</span>'
            f'<select data-lang-picker aria-label="Language">{options}</select></label>')


def localize_html(html: str, lang: str, version: str) -> str:
    """Set ``<html lang dir>`` and load the language pack and translator before page scripts."""
    lang = normalize_lang(lang)
    direction = LANGUAGES[lang][1]
    html = re.sub(r"<html lang=\"en\"", f'<html lang="{lang}" dir="{direction}"', html, count=1)
    tags = []
    if lang != "en":
        tags.append(f'<link rel="stylesheet" href="{ARABIC_FONT}">' if lang == "ar" else "")
        tags.append(f'<script src="/static/js/i18n/{lang}.js?v={version}"></script>')
    tags.append(f'<script src="/static/js/i18n.js?v={version}"></script>')
    return html.replace("</head>", "".join(tags) + "\n</head>", 1)
