"""Emails (candidates and employees) and in-app notifications.

Email backends (``HRM_EMAIL_BACKEND``):
- ``console``: prints the email and saves an .html copy in ``data/outbox/`` (local default)
- ``smtp``:    any SMTP server (Gmail app password, Mailtrap, SES SMTP endpoint)
- ``ses``:     Amazon SES API via the ECS task role (production on AWS)

Every attempt is written to ``email_log``; a failure is logged, never raised, so a mail
outage cannot break hiring, onboarding or leave workflows.
"""
from __future__ import annotations

import html
import logging
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

from . import db
from .settings import get_settings

logger = logging.getLogger("hr_management.email")
BRAND = "#008081"


@dataclass(frozen=True)
class Email:
    kind: str
    to: str
    subject: str
    html: str
    text: str


# kind -> (subject, headline, paragraphs, button label, button path)
_TEMPLATES: dict[str, tuple[str, str, tuple[str, ...], str, str]] = {
    "otp": (
        "Your {company} Careers sign-in code: {code}",
        "Your sign-in code",
        ("Use this code to sign in to the {company} Careers portal:",
         "<div style='font-size:34px;letter-spacing:10px;font-weight:700;margin:12px 0'>{code}</div>",
         "It expires in {ttl} minutes. If you did not request it, you can ignore this email."),
        "", "",
    ),
    "test_invite": (
        "You're shortlisted for the {role} mock test",
        "Congratulations, {name}! Your resume has been shortlisted.",
        ("Your resume scored <b>{score}</b> against the <b>{role}</b> requirements (qualifying score: {threshold}).",
         "The next round is a timed <b>Mock Test</b> on the skills this role needs. Take it when you have uninterrupted time — the timer starts as soon as you begin.",
         "You need {next_threshold}% or more to move on to the interview round."),
        "Start the mock test", "/careers",
    ),
    "ats_rejection": (
        "Update on your {role} application at {company}",
        "Thank you for applying, {name}.",
        ("We reviewed your resume for the <b>{role}</b> role. It scored <b>{score}</b>, below the qualifying score of {threshold}, so we will not be moving forward with your application at this time.",
         "We encourage you to apply for future openings that match your experience."),
        "", "",
    ),
    "interview_invite": (
        "You've qualified for the {role} interview round",
        "Great work, {name}! You passed the mock test.",
        ("You scored <b>{score}%</b> in the <b>{role}</b> mock test (qualifying score: {threshold}%).",
         "The next round is the <b>AI Interview</b>, based on the {role} role. You can answer by typing or speaking; coding questions open an editor.",
         "You need a score of {next_threshold} or more to clear the interview."),
        "Start the interview", "/careers",
    ),
    "test_rejection": (
        "Update on your {role} application at {company}",
        "Thank you for taking the mock test, {name}.",
        ("You scored <b>{score}%</b> in the <b>{role}</b> mock test, below the qualifying score of {threshold}%. We will not be moving forward with your application at this time.",
         "We appreciate the time you invested and encourage you to apply for future openings."),
        "", "",
    ),
    "interview_thanks": (
        "Thank you for attending the {role} interview",
        "Thank you for attending the interview, {name}!",
        ("You cleared the <b>{role}</b> interview round with a score of <b>{score}</b>.",
         "Our HR team is reviewing your results and will share the <b>next steps</b> with you soon."),
        "View your application", "/careers",
    ),
    "interview_rejection": (
        "Update on your {role} application at {company}",
        "Thank you for attending the interview, {name}.",
        ("Your interview for the <b>{role}</b> role scored <b>{score}</b>, below the qualifying score of {threshold}. We will not be moving forward with your application at this time.",
         "Thank you for the effort you put into every round."),
        "", "",
    ),
    "selected": (
        "Congratulations! You've been selected for {role} at {company}",
        "Welcome aboard, {name}! You have been selected.",
        ("We are delighted to offer you the <b>{role}</b> position at {company}.",
         "Please complete your <b>onboarding form</b>. Most of it is already filled in from your resume — check every field, edit anything that is wrong, add the remaining details and submit.",
         "Once you submit, you will receive your employee user ID and a temporary password by email."),
        "Complete onboarding", "/careers",
    ),
    "not_selected": (
        "Update on your {role} application at {company}",
        "Thank you, {name}.",
        ("After reviewing all rounds for the <b>{role}</b> role, we will not be moving forward with your application at this time.",
         "We appreciate your interest in {company} and encourage you to apply again."),
        "", "",
    ),
    "welcome_credentials": (
        "Your {company} employee account is ready",
        "Welcome to {company}, {name}!",
        ("Your onboarding is complete and your employee account has been created.",
         "<table style='border-collapse:collapse;margin:6px 0 14px'><tr><td style='padding:6px 14px 6px 0;color:#5b6b73'>Employee ID</td><td style='font-weight:700'>{employee_code}</td></tr>"
         "<tr><td style='padding:6px 14px 6px 0;color:#5b6b73'>User ID</td><td style='font-weight:700;font-family:monospace;font-size:16px'>{user_id}</td></tr>"
         "<tr><td style='padding:6px 14px 6px 0;color:#5b6b73'>Temporary password</td><td style='font-weight:700;font-family:monospace;font-size:16px'>{password}</td></tr></table>",
         "You will be asked to set your own password the first time you sign in. Never share your password with anyone, including HR."),
        "Sign in to the employee portal", "/login",
    ),
    "staff_credentials": (
        "Your {company} HR portal account",
        "Hello {name},",
        ("An HR portal account has been created for you.",
         "User ID: <b style='font-family:monospace'>{user_id}</b><br>Temporary password: <b style='font-family:monospace'>{password}</b>",
         "You will be asked to set your own password the first time you sign in."),
        "Sign in", "/login",
    ),
    "password_reset": (
        "Your {company} portal password was reset",
        "Hello {name},",
        ("HR has reset your portal password.",
         "User ID: <b style='font-family:monospace'>{user_id}</b><br>Temporary password: <b style='font-family:monospace'>{password}</b>",
         "You will be asked to set a new password when you sign in. If you did not ask for this, contact HR immediately."),
        "Sign in", "/login",
    ),
    "leave_pending": (
        "Leave request from {employee}: {leave_type}, {dates}",
        "{employee} has requested leave.",
        ("<b>{leave_type}</b> for <b>{days}</b> day(s): {dates}.", "Reason: {reason}"),
        "Review the request", "/me#/team",
    ),
    "leave_decision": (
        "Your leave request was {decision}",
        "Hello {name}, your leave request was {decision}.",
        ("<b>{leave_type}</b> for <b>{days}</b> day(s): {dates}.", "{note}"),
        "Open the employee portal", "/me#/leave",
    ),
    "request_update": (
        "Update on {ref}: {subject}",
        "Hello {name}, your request {ref} is now {status}.",
        ("{resolution}",),
        "View the request", "/me#/requests",
    ),
}


def format_score(value: float | None) -> str:
    if value is None or value == "":
        return ""
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def render(kind: str, to: str, **context: object) -> Email:
    cfg = get_settings()
    subject_t, headline_t, paragraphs_t, button, path = _TEMPLATES[kind]
    values = {"company": cfg.company_name, "ttl": cfg.otp_ttl_minutes, "name": "there", **context}
    safe = {key: html.escape(str(value)) for key, value in values.items()}
    subject = subject_t.format(**values)
    headline = headline_t.format(**safe)
    body = "".join(f"<p style='margin:0 0 14px;line-height:1.6'>{p.format(**safe)}</p>" for p in paragraphs_t)
    link = f"{cfg.public_base_url}{path}"
    button_html = (
        f"<a href='{link}' style='display:inline-block;background:{BRAND};color:#fff;text-decoration:none;"
        f"padding:12px 22px;border-radius:8px;font-weight:600;margin-top:6px'>{html.escape(button)}</a>" if button else ""
    )
    logo = f"{cfg.public_base_url}/static/img/kairoz-logo-white.png"
    html_body = f"""<!doctype html><html><body style="margin:0;background:#eef3f3;font-family:Segoe UI,Arial,sans-serif;color:#102a2e">
<div style="max-width:580px;margin:28px auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #d9e4e4">
  <div style="background:{BRAND};padding:18px 28px"><img src="{logo}" alt="{html.escape(cfg.company_name)}" height="34" style="display:block;height:34px"></div>
  <div style="padding:28px">
    <h2 style="margin:0 0 16px;font-size:21px;font-family:Georgia,serif">{headline}</h2>
    {body}
    {button_html}
  </div>
  <div style="padding:16px 28px;background:#f4f8f8;color:#5b6b73;font-size:12px">This is an automated message from {html.escape(cfg.company_name)} HR. Please do not reply.</div>
</div></body></html>"""
    text = re.sub(r"<br\s*/?>", "\n", "\n\n".join([headline_t.format(**values)] + [p.format(**values) for p in paragraphs_t]))
    text = re.sub(r"</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    if button:
        text += f"\n\n{button}: {link}"
    return Email(kind=kind, to=to, subject=subject, html=html_body, text=html.unescape(re.sub(r"[ \t]+", " ", text)))


def send(email: Email, *, application_id: int | None = None) -> bool:
    """Send (or print) one email and log the attempt. Never raises."""
    cfg = get_settings()
    backend = cfg.email_backend if cfg.email_backend in {"smtp", "ses"} else "console"
    try:
        {"smtp": _send_smtp, "ses": _send_ses}.get(backend, _send_console)(email)
        db.log_email(application_id=application_id, recipient=email.to, kind=email.kind, subject=_log_subject(email),
                     backend=backend, status="sent")
        return True
    except Exception as exc:  # noqa: BLE001 - surfaced on the HR email log
        logger.exception("Email %s to %s failed", email.kind, email.to)
        db.log_email(application_id=application_id, recipient=email.to, kind=email.kind, subject=_log_subject(email),
                     backend=backend, status="failed", error=str(exc))
        return False


def _log_subject(email: Email) -> str:
    # Never store sign-in codes in the log.
    return re.sub(r"\b\d{6}\b", "••••••", email.subject)


def send_stage_email(kind: str, application: dict, *, score: float, threshold: float, next_threshold: float | None = None) -> bool:
    email = render(
        kind, application["email"],
        name=(application.get("full_name") or "there").split(" ")[0],
        role=application["role_title"],
        score=format_score(score), threshold=format_score(threshold),
        next_threshold=format_score(next_threshold) if next_threshold is not None else "",
    )
    return send(email, application_id=int(application["id"]))


def send_template(kind: str, to: str, *, application_id: int | None = None, **context: object) -> bool:
    return send(render(kind, to, **context), application_id=application_id)


# ---- in-app notifications ---------------------------------------------------------------

def notify(account_id: int | None, title: str, body: str = "", link: str = "") -> None:
    if not account_id:
        return
    db.insert("notifications", {"account_id": int(account_id), "title": title[:200], "body": body[:1000], "link": link,
                                "is_read": 0, "created_at": db.now_iso()})


def notify_hr(title: str, body: str = "", link: str = "") -> None:
    for row in db.fetch_all("SELECT id FROM accounts WHERE role IN ('hr_admin', 'hr') AND is_active = 1"):
        notify(row["id"], title, body, link)


# ---- backends ---------------------------------------------------------------------------

def _sender() -> str:
    cfg = get_settings()
    address = cfg.email_from or cfg.smtp_username or f"no-reply@{cfg.company_name.lower()}.com"
    return address if "<" in address else f"{cfg.company_name} HR <{address}>"


def _send_smtp(email: Email) -> None:
    cfg = get_settings()
    if not cfg.smtp_host:
        raise RuntimeError("HRM_EMAIL_BACKEND=smtp but HRM_SMTP_HOST is not set.")
    message = EmailMessage()
    message["From"] = _sender()
    message["To"] = email.to
    message["Subject"] = email.subject
    message.set_content(email.text)
    message.add_alternative(email.html, subtype="html")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as server:
        if cfg.smtp_use_tls:
            server.starttls()
        if cfg.smtp_username:
            server.login(cfg.smtp_username, cfg.smtp_password)
        server.send_message(message)


def _send_ses(email: Email) -> None:
    import boto3

    cfg = get_settings()
    boto3.client("ses", region_name=cfg.aws_region).send_email(
        Source=_sender(),
        Destination={"ToAddresses": [email.to]},
        Message={
            "Subject": {"Data": email.subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": email.text, "Charset": "UTF-8"}, "Html": {"Data": email.html, "Charset": "UTF-8"}},
        },
    )


def _send_console(email: Email) -> None:
    cfg = get_settings()
    cfg.outbox_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_to = re.sub(r"[^a-z0-9]+", "_", email.to.lower())
    path = cfg.outbox_dir / f"{stamp}_{email.kind}_{safe_to}.html"
    path.write_text(email.html, encoding="utf-8")
    bar = "─" * 64
    print(f"\n{bar}\n📧  EMAIL ({email.kind})\nTo:      {email.to}\nSubject: {email.subject}\n\n{email.text}\n\nSaved:   {path}\n{bar}\n", flush=True)
