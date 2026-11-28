"""English / Arabic: page language, saved preference, Arabic emails, Arabic assistant, language pack integrity."""
import json
import re
import string
from pathlib import Path

from conftest import staff_client
from hr_management import db, notifications
from hr_management.services import accounts

STATIC = Path(__file__).resolve().parents[1] / "src" / "hr_management" / "static"


def _html_lang(response) -> tuple[str, str]:
    m = re.search(r'<html lang="(\w+)"(?: dir="(\w+)")?', response.text)
    return m.group(1), m.group(2) or "ltr"


def test_page_language_from_cookie_browser_and_default(app):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert _html_lang(client.get("/login")) == ("en", "ltr")
    assert "/static/js/i18n/ar.js" not in client.get("/login").text
    assert 'data-lang-picker' in client.get("/login").text and 'data-lang-picker' in client.get("/").text

    browser_ar = client.get("/login", headers={"accept-language": "ar-SA,ar;q=0.9,en;q=0.5"})
    assert _html_lang(browser_ar) == ("ar", "rtl") and "/static/js/i18n/ar.js" in browser_ar.text

    client.cookies.set("hrm_lang", "en")  # an explicit choice beats the browser
    assert _html_lang(client.get("/login", headers={"accept-language": "ar"})) == ("en", "ltr")
    client.cookies.set("hrm_lang", "ar")
    page = client.get("/careers/login")
    assert _html_lang(page) == ("ar", "rtl") and page.headers["content-language"] == "ar"
    client.cookies.set("hrm_lang", "xx")  # unknown value falls back safely
    assert _html_lang(client.get("/login")) == ("en", "ltr")


def test_language_choice_is_saved_and_used_for_emails(app, hr_client):
    created = hr_client.post("/api/hr/employees", json={"full_name": "Layla Haddad", "email": "layla@example.com", "designation": "Analyst",
                                                         "department": "Finance", "date_of_joining": "2026-01-05", "annual_ctc": 900000}).json()
    employee = created["employee"]
    password = accounts.reset_password(employee["account_id"], actor={"user_id": "test", "role": "hr_admin"})
    client = staff_client(app, employee["employee_code"], password, change_to="Sunrise2026x")

    r = client.post("/api/auth/language", json={"lang": "ar"})
    assert r.status_code == 200 and r.json() == {"lang": "ar"}
    assert db.fetch_one("SELECT lang FROM accounts WHERE id = ?", (employee["account_id"],))["lang"] == "ar"
    assert client.get("/api/auth/me").json()["lang"] == "ar"
    assert client.post("/api/auth/language", json={"lang": "fr"}).status_code == 400

    # A new device with no cookie still opens in Arabic for this person.
    fresh = staff_client(app, employee["employee_code"], "Sunrise2026x")
    fresh.cookies.delete("hrm_lang")
    assert _html_lang(fresh.get("/me")) == ("ar", "rtl")

    # HR resets the password → the email goes out in Arabic, right-to-left.
    accounts.reset_password(employee["account_id"], actor={"user_id": "test", "role": "hr_admin"})
    email = notifications.render("password_reset", "layla@example.com", name="Layla", user_id=employee["employee_code"], password="x")
    assert 'dir="rtl"' in email.html and "كلمة مرور" in email.subject
    assert notifications.render("password_reset", "someone.else@example.com", name="A", user_id="KZE1", password="x").subject.startswith("Your")


def test_candidate_code_email_follows_page_language(app):
    from fastapi.testclient import TestClient

    from hr_management.settings import get_settings

    client = TestClient(app)
    client.cookies.set("hrm_lang", "ar")
    assert client.post("/api/auth/request-otp", json={"email": "amal@example.com"}).status_code == 200
    sent = sorted(get_settings().outbox_dir.glob("*otp*"))[-1].read_text(encoding="utf-8")
    assert 'dir="rtl"' in sent and "رمز" in sent
    otp = client.post("/api/auth/request-otp", json={"email": "amal@example.com"}).json()["dev_otp"]
    assert client.post("/api/auth/verify", json={"email": "amal@example.com", "otp": otp}).status_code == 200
    assert db.fetch_one("SELECT lang FROM users WHERE email = ?", ("amal@example.com",))["lang"] == "ar"


def test_arabic_email_templates_match_english():
    for kind, (subject, headline, paragraphs, button, _path) in notifications._TEMPLATES.items():
        assert kind in notifications._TEMPLATES_AR, kind
        ar_subject, ar_headline, ar_paragraphs, ar_button = notifications._TEMPLATES_AR[kind]
        fields = lambda *texts: {f for t in texts for _, f, _, _ in string.Formatter().parse(t) if f}  # noqa: E731
        assert fields(subject, headline, *paragraphs) == fields(ar_subject, ar_headline, *ar_paragraphs), kind
        assert bool(button) == bool(ar_button), kind


def test_assistant_understands_and_answers_arabic(app, hr_client):
    created = hr_client.post("/api/hr/employees", json={"full_name": "Omar Saleh", "email": "omar@example.com", "designation": "Engineer",
                                                         "department": "Engineering", "date_of_joining": "2024-01-08", "annual_ctc": 1200000}).json()
    employee = created["employee"]
    password = accounts.reset_password(employee["account_id"], actor={"user_id": "test", "role": "hr_admin"})
    client = staff_client(app, employee["employee_code"], password, change_to="Sunrise2026x")
    client.cookies.set("hrm_lang", "ar")

    balance = client.post("/api/me/assistant", json={"message": "كم رصيد إجازاتي؟"}).json()
    assert balance["tool"] == "leave_balance" and "رصيد" in balance["reply"]
    leave = client.post("/api/me/assistant", json={"message": "إجازة مرضية اليوم"}).json()
    assert leave["tool"] == "check_leave"
    doc = client.post("/api/me/assistant", json={"message": "أحتاج شهادة عمل"}).json()
    assert doc["tool"] == "request_document" and doc["action"]["args"]["document_type"] == "Employment certificate"
    assert re.search(r"[؀-ۿ]", doc["action"]["label"])
    done = client.post("/api/me/assistant/confirm", json={"action": doc["action"]}).json()
    assert "تم" in done["reply"]

    client.cookies.set("hrm_lang", "en")  # same question, English page → English reply
    assert client.post("/api/me/assistant", json={"message": "how many leaves do I have left?"}).json()["reply"].startswith("Here is your leave balance")


def test_arabic_language_pack_is_valid():
    source = (STATIC / "js" / "i18n" / "ar.js").read_text(encoding="utf-8")
    pack = json.loads(source[source.index("{"): source.rindex("}") + 1])
    assert pack["lang"] == "ar" and len(pack["strings"]) > 900
    for english, arabic in pack["strings"].items():
        assert arabic.strip(), english
    for source_pattern, template in pack["patterns"]:
        compiled = re.compile(f"^{source_pattern}$")
        groups = compiled.groups
        for ref in re.findall(r"\$[LS]?(\d)", template):
            assert int(ref) <= groups, (source_pattern, template)
    js = (STATIC / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "hrm_lang" in js and "/api/auth/language" in js
