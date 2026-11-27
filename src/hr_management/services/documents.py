"""Employment documents generated on request (stored via ``storage``, listed in My documents).

Documents are printable HTML (employees use the browser's "Save as PDF"). This keeps the
container free of PDF/font toolchains; a PDF renderer can be swapped in here later.
"""
from __future__ import annotations

import html
from datetime import date

from .. import db, storage
from ..settings import get_settings
from . import ServiceError
from .payroll import inr

TEMPLATES = {
    "Employment certificate": "This is to certify that <b>{name}</b> (Employee ID {code}) has been employed with {company} since "
                              "<b>{joined}</b> and is currently working as <b>{designation}</b> in the {department} department.",
    "Salary certificate": "This is to certify that <b>{name}</b> (Employee ID {code}), working as <b>{designation}</b> since {joined}, "
                          "draws an annual cost-to-company of <b>₹{ctc}</b>.",
    "Address proof letter": "This is to certify that <b>{name}</b> (Employee ID {code}) is employed with {company} as {designation}. "
                            "As per our records, the residential address of the employee is: <b>{address}</b>.",
    "Experience letter": "This is to certify that <b>{name}</b> (Employee ID {code}) worked with {company} as <b>{designation}</b> "
                         "from {joined} to {exit}. During this period we found the employee sincere and professional.",
}


def _render(employee: dict, kind: str) -> str:
    cfg = get_settings()
    body = TEMPLATES[kind].format(
        name=html.escape(employee["full_name"]), code=html.escape(employee["employee_code"]), company=html.escape(cfg.company_name),
        joined=html.escape(employee["date_of_joining"]), designation=html.escape(employee["designation"]),
        department=html.escape(employee["department"] or "—"), ctc=inr(employee["annual_ctc"] or 0).lstrip("₹"),
        address=html.escape(employee["address"] or "—"), exit=html.escape(employee.get("exit_date") or "date"),
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(kind)} – {html.escape(employee['full_name'])}</title>
<style>body{{font-family:Georgia,serif;color:#102a2e;max-width:720px;margin:40px auto;padding:0 24px;line-height:1.7}}
header{{background:#008081;padding:18px 24px;border-radius:6px}} header img{{height:40px}}
h1{{font-size:22px;margin:36px 0 8px}} .meta{{color:#5b6b73;font-size:14px}} footer{{margin-top:60px}}
@media print{{header{{-webkit-print-color-adjust:exact;print-color-adjust:exact}} button{{display:none}}}}</style></head>
<body><header><img src="{cfg.public_base_url}/static/img/kairoz-logo-white.png" alt="{html.escape(cfg.company_name)}"></header>
<p class="meta">Date: {date.today().strftime('%d %B %Y')}<br>Ref: {html.escape(employee['employee_code'])}/{kind[:3].upper()}/{date.today().strftime('%Y%m%d')}</p>
<h1>{html.escape(kind)}</h1><p>To whom it may concern,</p><p>{body}</p>
<p>This letter is issued on the employee's request for official purposes.</p>
<footer><p>For {html.escape(cfg.company_name)} Corporation<br><br><b>Human Resources</b></p>
<button onclick="window.print()">Print / Save as PDF</button></footer></body></html>"""


def generate(employee_id: int, kind: str, *, actor: str) -> dict:
    if kind not in TEMPLATES:
        raise ServiceError("Unknown document type.")
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
    if not employee:
        raise ServiceError("Employee not found.", 404)
    key = storage.put(storage.new_key(f"documents/{employee['employee_code']}", f"{kind}.html"),
                      _render(employee, kind).encode(), "text/html; charset=utf-8")
    doc_id = db.insert("documents", {"employee_id": employee_id, "kind": "generated", "title": kind, "storage_key": key,
                                     "content_type": "text/html", "created_at": db.now_iso()})
    db.audit(actor, "document_generated", "employee", employee_id, {"title": kind})
    return db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))  # type: ignore[return-value]


def for_employee(employee_id: int) -> list[dict]:
    return db.fetch_all("SELECT id, kind, title, created_at FROM documents WHERE employee_id = ? ORDER BY id DESC", (employee_id,))


def read(doc_id: int, employee_id: int | None = None) -> tuple[dict, bytes]:
    doc = db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not doc or (employee_id is not None and doc["employee_id"] != employee_id):
        raise ServiceError("Document not found.", 404)
    return doc, storage.get(doc["storage_key"])


def payslip_html(slip: dict, employee: dict) -> str:
    """Printable payslip (employees use "Save as PDF")."""
    from datetime import date as _date

    from .payroll import explain

    cfg = get_settings()
    year, month = (int(x) for x in slip["period"].split("-"))
    title = _date(year, month, 1).strftime("%B %Y")
    rows_e = "".join(f"<tr><td>{html.escape(k)}</td><td class='n'>{inr(v)}</td></tr>" for k, v in (slip.get("earnings") or {}).items())
    rows_d = "".join(f"<tr><td>{html.escape(k)}</td><td class='n'>{inr(v)}</td></tr>" for k, v in (slip.get("deductions") or {}).items()) \
        or "<tr><td>None</td><td class='n'>₹0.00</td></tr>"
    notes = "".join(f"<li>{html.escape(line)}</li>" for line in explain(slip))
    from .people import mask

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Payslip {title} – {html.escape(employee['full_name'])}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;color:#102a2e;max-width:780px;margin:30px auto;padding:0 20px}}
header{{background:#008081;color:#fff;padding:16px 22px;border-radius:6px;display:flex;justify-content:space-between;align-items:center}}
header img{{height:36px}} h1{{font-size:20px;margin:24px 0 6px}} table{{width:100%;border-collapse:collapse;margin-top:8px}}
td,th{{padding:8px 10px;border-bottom:1px solid #dde6e6;text-align:left;font-size:14px}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}} .meta td{{border:0;padding:3px 10px 3px 0}} .net{{font-size:20px;font-weight:700;margin-top:18px}}
ul{{color:#43575e;font-size:13px}} @media print{{header{{-webkit-print-color-adjust:exact;print-color-adjust:exact}} button{{display:none}}}}</style></head>
<body><header><img src="/static/img/kairoz-logo-white.png" alt="{html.escape(cfg.company_name)}"><span>Payslip – {title}</span></header>
<table class="meta"><tr><td>Employee</td><td><b>{html.escape(employee['full_name'])}</b> ({html.escape(employee['employee_code'])})</td>
<td>Designation</td><td>{html.escape(employee['designation'])}</td></tr>
<tr><td>Department</td><td>{html.escape(employee['department'] or '—')}</td><td>Bank A/C</td><td>{mask(employee.get('bank_account_number', ''))}</td></tr>
<tr><td>Working days</td><td>{slip['working_days']:g}</td><td>Paid days</td><td>{slip['paid_days']:g} (LOP {slip['lop_days']:g})</td></tr></table>
<div class="grid"><div><h1>Earnings</h1><table>{rows_e}<tr><th>Gross</th><th class='n'>{inr(slip['gross'])}</th></tr></table></div>
<div><h1>Deductions</h1><table>{rows_d}<tr><th>Total</th><th class='n'>{inr(slip['total_deductions'])}</th></tr></table></div></div>
<p class="net">Net pay: {inr(slip['net_pay'])}</p><h1>How this was calculated</h1><ul>{notes}</ul>
<button onclick="window.print()">Print / Save as PDF</button></body></html>"""
