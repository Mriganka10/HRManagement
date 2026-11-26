"""Candidate emails: templates plus a pluggable sender.

Backends (``HRM_EMAIL_BACKEND``):
- ``console`` (default locally): prints the email in the terminal and saves an .html copy
  under ``data/outbox/`` so you can open it in a browser.
- ``smtp``: sends through any SMTP server (Gmail app password, SES SMTP, Mailtrap...).
  An AWS SES API backend can be added here later without touching the callers.

Every attempt is written to the ``email_log`` table, which HR can see on the board.
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


@dataclass(frozen=True)
class Email:
    kind: str
    to: str
    subject: str
    html: str
    text: str


# kind -> (subject, accent colour, headline, body paragraphs, button label or "")
_TEMPLATES: dict[str, tuple[str, str, str, tuple[str, ...], str]] = {
    "otp": (
        "Your {company} sign-in code: {code}",
        "#6d5efc",
        "Your sign-in code",
        ("Use this code to sign in to the {company} Careers portal:",
         "<div style='font-size:34px;letter-spacing:10px;font-weight:700;margin:12px 0'>{code}</div>",
         "It expires in {ttl} minutes. If you did not request it, you can ignore this email."),
        "",
    ),
    "test_invite": (
        "You're shortlisted for the {role} mock test",
        "#16a34a",
        "Congratulations, {name}! You cleared the resume screen.",
        ("Your resume scored <b>{score}</b> on our ATS screen for the <b>{role}</b> role "
         "(qualifying score: {threshold}).",
         "You are now eligible for the <b>Mock Test</b>. It is a timed multiple-choice test on the "
         "skills this role needs. Take it when you have uninterrupted time — the timer starts as soon as you begin.",
         "You need {next_threshold}% or more to move on to the interview round."),
        "Start the mock test",
    ),
    "ats_rejection": (
        "Update on your {role} application",
        "#64748b",
        "Thank you for applying, {name}.",
        ("We reviewed your resume for the <b>{role}</b> role. It scored <b>{score}</b> on our ATS screen, "
         "below the qualifying score of {threshold}, so we will not be moving forward with your application at this time.",
         "Your profile stays with us, and we encourage you to apply for future openings that match your experience."),
        "",
    ),
    "interview_invite": (
        "You've qualified for the {role} interview round",
        "#16a34a",
        "Great work, {name}! You passed the mock test.",
        ("You scored <b>{score}%</b> in the <b>{role}</b> mock test (qualifying score: {threshold}%).",
         "You are now eligible for the <b>Mock Interview</b>. Questions are based on the {role} role; you can "
         "answer by typing or by speaking, and coding questions open an editor.",
         "You need a score of {next_threshold} or more to clear the interview."),
        "Start the interview",
    ),
    "test_rejection": (
        "Update on your {role} application",
        "#64748b",
        "Thank you for taking the mock test, {name}.",
        ("You scored <b>{score}%</b> in the <b>{role}</b> mock test, below the qualifying score of {threshold}%. "
         "We will not be moving forward with your application at this time.",
         "We appreciate the time you invested and encourage you to apply for future openings."),
        "",
    ),
    "interview_thanks": (
        "Thank you for attending the {role} interview",
        "#6d5efc",
        "Thank you for attending the interview, {name}!",
        ("You cleared the <b>{role}</b> interview round with a score of <b>{score}</b>.",
         "Our HR team will review your results and share the <b>next steps</b> with you soon. "
         "Please keep an eye on your inbox."),
        "View your application",
    ),
    "interview_rejection": (
        "Update on your {role} application",
        "#64748b",
        "Thank you for attending the interview, {name}.",
        ("Your interview for the <b>{role}</b> role scored <b>{score}</b>, below the qualifying score of {threshold}. "
         "We will not be moving forward with your application at this time.",
         "Thank you for the time and effort you put into every round. We encourage you to apply again in future."),
        "",
    ),
}


def render(kind: str, to: str, **context: object) -> Email:
    cfg = get_settings()
    subject_t, accent, headline_t, paragraphs_t, button = _TEMPLATES[kind]
    values = {"company": cfg.company_name, "ttl": cfg.otp_ttl_minutes, "name": "there", **context}
    # Escape candidate-provided values; templates themselves contain trusted markup.
    safe = {key: html.escape(str(value)) for key, value in values.items()}
    subject = subject_t.format(**values)
    headline = headline_t.format(**safe)
    body = "".join(f"<p style='margin:0 0 14px;line-height:1.6'>{p.format(**safe)}</p>" for p in paragraphs_t)
    link = f"{cfg.public_base_url}/app"
    button_html = (
        f"<a href='{link}' style='display:inline-block;background:{accent};color:#fff;text-decoration:none;"
        f"padding:12px 22px;border-radius:10px;font-weight:600;margin-top:6px'>{html.escape(button)}</a>" if button else ""
    )
    html_body = f"""<!doctype html><html><body style="margin:0;background:#f4f5fb;font-family:Segoe UI,Arial,sans-serif;color:#1e1b4b">
<div style="max-width:560px;margin:28px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 6px 30px rgba(30,27,75,.08)">
  <div style="background:linear-gradient(120deg,{accent},#22d3ee);padding:22px 28px;color:#fff;font-weight:700;font-size:18px">{html.escape(cfg.company_name)} Careers</div>
  <div style="padding:28px">
    <h2 style="margin:0 0 16px;font-size:21px">{headline}</h2>
    {body}
    {button_html}
  </div>
  <div style="padding:16px 28px;background:#f8f9fe;color:#64748b;font-size:12px">This is an automated message from the {html.escape(cfg.company_name)} hiring team.</div>
</div></body></html>"""
    text = re.sub(r"<[^>]+>", "", f"{headline}\n\n" + "\n\n".join(p.format(**values) for p in paragraphs_t))
    if button:
        text += f"\n\n{button}: {link}"
    return Email(kind=kind, to=to, subject=subject, html=html_body, text=html.unescape(text))


def send(email: Email, *, application_id: int | None = None) -> bool:
    """Send (or print) one email and log the attempt. Never raises: a mail outage must not break the pipeline."""
    cfg = get_settings()
    backend = cfg.email_backend
    try:
        if backend == "smtp":
            _send_smtp(email)
        else:
            backend = "console"
            _send_console(email)
        db.log_email(application_id=application_id, recipient=email.to, kind=email.kind, subject=email.subject, backend=backend, status="sent")
        return True
    except Exception as exc:  # noqa: BLE001 - logged and surfaced on the HR board
        logger.exception("Email %s to %s failed", email.kind, email.to)
        db.log_email(application_id=application_id, recipient=email.to, kind=email.kind, subject=email.subject, backend=backend,
                     status="failed", error=str(exc))
        return False


def send_stage_email(kind: str, application: dict, *, score: float, threshold: float, next_threshold: float | None = None) -> bool:
    email = render(
        kind,
        application["email"],
        name=(application.get("full_name") or "there").split(" ")[0],
        role=application["role_title"],
        score=format_score(score),
        threshold=format_score(threshold),
        next_threshold=format_score(next_threshold) if next_threshold is not None else "",
    )
    return send(email, application_id=int(application["id"]))


def format_score(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{float(value):.1f}"


def _send_smtp(email: Email) -> None:
    cfg = get_settings()
    if not cfg.smtp_host:
        raise RuntimeError("HRM_EMAIL_BACKEND=smtp but HRM_SMTP_HOST is not set.")
    message = EmailMessage()
    message["From"] = cfg.smtp_from or cfg.smtp_username
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


def _send_console(email: Email) -> None:
    cfg = get_settings()
    cfg.outbox_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_to = re.sub(r"[^a-z0-9]+", "_", email.to.lower())
    path = cfg.outbox_dir / f"{stamp}_{email.kind}_{safe_to}.html"
    path.write_text(email.html, encoding="utf-8")
    bar = "─" * 64
    print(f"\n{bar}\n📧  EMAIL ({email.kind})\nTo:      {email.to}\nSubject: {email.subject}\n\n{email.text}\n\nSaved:   {path}\n{bar}\n", flush=True)
