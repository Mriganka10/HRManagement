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
        "Sign in to the employee portal", "/login?as=employee",
    ),
    "staff_credentials": (
        "Your {company} HR portal account",
        "Hello {name},",
        ("An HR portal account has been created for you.",
         "User ID: <b style='font-family:monospace'>{user_id}</b><br>Temporary password: <b style='font-family:monospace'>{password}</b>",
         "You will be asked to set your own password the first time you sign in."),
        "Sign in", "/login?as=hr",
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


# Arabic versions of the same emails (sent when the recipient's saved language is Arabic).
# Placeholders are identical to the English templates; values such as role titles, names and
# dates are data and stay as entered.
_TEMPLATES_AR: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "otp": (
        "رمز تسجيل الدخول إلى بوابة الوظائف في {company}: {code}",
        "رمز تسجيل الدخول",
        ("استخدم هذا الرمز لتسجيل الدخول إلى بوابة الوظائف في {company}:",
         "<div style='font-size:34px;letter-spacing:10px;font-weight:700;margin:12px 0' dir='ltr'>{code}</div>",
         "تنتهي صلاحيته خلال {ttl} دقيقة. إذا لم تطلب هذا الرمز، يمكنك تجاهل هذه الرسالة."),
        "",
    ),
    "test_invite": (
        "تم ترشيحك للاختبار التجريبي لوظيفة {role}",
        "تهانينا يا {name}! تم ترشيح سيرتك الذاتية.",
        ("حصلت سيرتك الذاتية على <b>{score}</b> مقارنةً بمتطلبات وظيفة <b>{role}</b> (درجة التأهل: {threshold}).",
         "الجولة التالية هي <b>اختبار تجريبي</b> محدد الوقت في المهارات التي تتطلبها هذه الوظيفة. أدِّه عندما يتوفر لديك وقت دون مقاطعة، فالمؤقت يبدأ بمجرد أن تبدأ.",
         "تحتاج إلى {next_threshold}% أو أكثر للانتقال إلى جولة المقابلة."),
        "ابدأ الاختبار التجريبي",
    ),
    "ats_rejection": (
        "تحديث بشأن طلبك لوظيفة {role} في {company}",
        "شكرًا لتقدمك يا {name}.",
        ("راجعنا سيرتك الذاتية لوظيفة <b>{role}</b>. حصلت على <b>{score}</b>، وهي أقل من درجة التأهل البالغة {threshold}، لذا لن نمضي قدمًا في طلبك في الوقت الحالي.",
         "نشجعك على التقدم للوظائف المستقبلية التي تناسب خبرتك."),
        "",
    ),
    "interview_invite": (
        "تأهلت لجولة المقابلة لوظيفة {role}",
        "أحسنت يا {name}! لقد اجتزت الاختبار التجريبي.",
        ("حصلت على <b>{score}%</b> في الاختبار التجريبي لوظيفة <b>{role}</b> (درجة التأهل: {threshold}%).",
         "الجولة التالية هي <b>المقابلة بالذكاء الاصطناعي</b> الخاصة بوظيفة {role}. يمكنك الإجابة بالكتابة أو بالصوت، وتفتح أسئلة البرمجة محرر الشيفرة.",
         "تحتاج إلى درجة {next_threshold} أو أكثر لاجتياز المقابلة."),
        "ابدأ المقابلة",
    ),
    "test_rejection": (
        "تحديث بشأن طلبك لوظيفة {role} في {company}",
        "شكرًا لأدائك الاختبار التجريبي يا {name}.",
        ("حصلت على <b>{score}%</b> في الاختبار التجريبي لوظيفة <b>{role}</b>، وهي أقل من درجة التأهل البالغة {threshold}%. لن نمضي قدمًا في طلبك في الوقت الحالي.",
         "نقدّر الوقت الذي بذلته ونشجعك على التقدم للوظائف المستقبلية."),
        "",
    ),
    "interview_thanks": (
        "شكرًا لحضورك مقابلة وظيفة {role}",
        "شكرًا لحضورك المقابلة يا {name}!",
        ("اجتزت جولة المقابلة لوظيفة <b>{role}</b> بدرجة <b>{score}</b>.",
         "يراجع فريق الموارد البشرية نتائجك وسيشاركك <b>الخطوات التالية</b> قريبًا."),
        "عرض طلبك",
    ),
    "interview_rejection": (
        "تحديث بشأن طلبك لوظيفة {role} في {company}",
        "شكرًا لحضورك المقابلة يا {name}.",
        ("حصلت مقابلتك لوظيفة <b>{role}</b> على <b>{score}</b>، وهي أقل من درجة التأهل البالغة {threshold}. لن نمضي قدمًا في طلبك في الوقت الحالي.",
         "شكرًا على الجهد الذي بذلته في كل جولة."),
        "",
    ),
    "selected": (
        "تهانينا! تم اختيارك لوظيفة {role} في {company}",
        "مرحبًا بك يا {name}! لقد تم اختيارك.",
        ("يسعدنا أن نعرض عليك وظيفة <b>{role}</b> في {company}.",
         "يرجى إكمال <b>نموذج الالتحاق</b>. معظمه مُعبّأ مسبقًا من سيرتك الذاتية — راجع كل حقل، وعدّل أي خطأ، وأضف البيانات المتبقية ثم أرسله.",
         "بعد الإرسال ستصلك رسالة بمعرّف المستخدم الخاص بك وكلمة مرور مؤقتة."),
        "أكمل الالتحاق",
    ),
    "not_selected": (
        "تحديث بشأن طلبك لوظيفة {role} في {company}",
        "شكرًا لك يا {name}.",
        ("بعد مراجعة جميع جولات وظيفة <b>{role}</b>، لن نمضي قدمًا في طلبك في الوقت الحالي.",
         "نقدّر اهتمامك بـ{company} ونشجعك على التقدم مجددًا."),
        "",
    ),
    "welcome_credentials": (
        "حسابك الوظيفي في {company} جاهز",
        "مرحبًا بك في {company} يا {name}!",
        ("اكتمل التحاقك وتم إنشاء حسابك الوظيفي.",
         "<table style='border-collapse:collapse;margin:6px 0 14px'><tr><td style='padding:6px 0 6px 14px;color:#5b6b73'>الرقم الوظيفي</td><td style='font-weight:700' dir='ltr'>{employee_code}</td></tr>"
         "<tr><td style='padding:6px 0 6px 14px;color:#5b6b73'>معرّف المستخدم</td><td style='font-weight:700;font-family:monospace;font-size:16px' dir='ltr'>{user_id}</td></tr>"
         "<tr><td style='padding:6px 0 6px 14px;color:#5b6b73'>كلمة المرور المؤقتة</td><td style='font-weight:700;font-family:monospace;font-size:16px' dir='ltr'>{password}</td></tr></table>",
         "سيُطلب منك تعيين كلمة مرور خاصة بك عند أول تسجيل دخول. لا تشارك كلمة المرور مع أي شخص، بما في ذلك الموارد البشرية."),
        "سجّل الدخول إلى بوابة الموظفين",
    ),
    "staff_credentials": (
        "حسابك في بوابة الموارد البشرية في {company}",
        "مرحبًا {name}،",
        ("تم إنشاء حساب لك في بوابة الموارد البشرية.",
         "معرّف المستخدم: <b style='font-family:monospace' dir='ltr'>{user_id}</b><br>كلمة المرور المؤقتة: <b style='font-family:monospace' dir='ltr'>{password}</b>",
         "سيُطلب منك تعيين كلمة مرور خاصة بك عند أول تسجيل دخول."),
        "تسجيل الدخول",
    ),
    "password_reset": (
        "تمت إعادة تعيين كلمة مرور بوابتك في {company}",
        "مرحبًا {name}،",
        ("أعادت الموارد البشرية تعيين كلمة مرور بوابتك.",
         "معرّف المستخدم: <b style='font-family:monospace' dir='ltr'>{user_id}</b><br>كلمة المرور المؤقتة: <b style='font-family:monospace' dir='ltr'>{password}</b>",
         "سيُطلب منك تعيين كلمة مرور جديدة عند تسجيل الدخول. إذا لم تطلب ذلك، فتواصل مع الموارد البشرية فورًا."),
        "تسجيل الدخول",
    ),
    "leave_pending": (
        "طلب إجازة من {employee}: {leave_type}، {dates}",
        "طلب {employee} إجازة.",
        ("<b>{leave_type}</b> لمدة <b>{days}</b> يوم: {dates}.", "السبب: {reason}"),
        "مراجعة الطلب",
    ),
    "leave_decision": (
        "تم {decision} طلب إجازتك",
        "مرحبًا {name}، تم {decision} طلب إجازتك.",
        ("<b>{leave_type}</b> لمدة <b>{days}</b> يوم: {dates}.", "{note}"),
        "افتح بوابة الموظفين",
    ),
    "request_update": (
        "تحديث بشأن {ref}: {subject}",
        "مرحبًا {name}، أصبحت حالة طلبك {ref}: {status}.",
        ("{resolution}",),
        "عرض الطلب",
    ),
}

# Words passed into templates as values that are interface text, not data.
_VALUE_AR = {
    "approved": "قبول", "rejected": "رفض", "cancelled": "إلغاء",
    "open": "مفتوح", "in_progress": "قيد التنفيذ", "in progress": "قيد التنفيذ", "resolved": "تم الحل", "closed": "مغلق",
    "Casual Leave": "إجازة عارضة", "Sick Leave": "إجازة مرضية", "Earned Leave": "إجازة مكتسبة",
    "Work From Home": "العمل من المنزل", "Leave Without Pay": "إجازة بدون راتب",
}
_FOOTER = {"en": "This is an automated message from {company} HR. Please do not reply.",
           "ar": "هذه رسالة آلية من الموارد البشرية في {company}. يرجى عدم الرد عليها."}


def format_score(value: float | None) -> str:
    if value is None or value == "":
        return ""
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def render(kind: str, to: str, *, lang: str | None = None, **context: object) -> Email:
    """Build one email in the recipient's language (``lang`` or their saved preference)."""
    from . import i18n

    cfg = get_settings()
    lang = i18n.normalize_lang(lang) if lang else i18n.lang_for_email(to)
    subject_t, headline_t, paragraphs_t, button, path = _TEMPLATES[kind]
    rtl = False
    if lang == "ar" and kind in _TEMPLATES_AR:
        subject_t, headline_t, paragraphs_t, button = _TEMPLATES_AR[kind]
        rtl = True
        context = {k: (_VALUE_AR.get(v, v) if isinstance(v, str) and k in {"decision", "status", "leave_type"} else v) for k, v in context.items()}
        if not context.get("name") or context.get("name") == "there":
            context["name"] = "عزيزي"
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
    direction = "rtl" if rtl else "ltr"
    footer = _FOOTER["ar" if rtl else "en"].format(company=html.escape(cfg.company_name))
    font = "Segoe UI,Tahoma,Arial,sans-serif" if rtl else "Segoe UI,Arial,sans-serif"
    html_body = f"""<!doctype html><html lang="{'ar' if rtl else 'en'}" dir="{direction}"><body style="margin:0;background:#eef3f3;font-family:{font};color:#102a2e;direction:{direction};text-align:{'right' if rtl else 'left'}">
<div style="max-width:580px;margin:28px auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #d9e4e4">
  <div style="background:{BRAND};padding:18px 28px"><img src="{logo}" alt="{html.escape(cfg.company_name)}" height="34" style="display:block;height:34px"></div>
  <div style="padding:28px">
    <h2 style="margin:0 0 16px;font-size:21px;font-family:{font if rtl else 'Georgia,serif'}">{headline}</h2>
    {body}
    {button_html}
  </div>
  <div style="padding:16px 28px;background:#f4f8f8;color:#5b6b73;font-size:12px">{footer}</div>
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
