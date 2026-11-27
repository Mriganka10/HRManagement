"""Performance check-ins (3, 6 and 12 months after joining, plus annual) and
**recruitment intelligence**: which recruitment signals predicted on-the-job performance.

For every hired employee with at least one review, we pair their recruitment scores
(ATS, mock test, interview, each competency) with their average review rating and compute
the Pearson correlation per signal. With enough hires this tells HR which assessment
parameters actually predict success in *this* organisation — the feedback loop described
in the product brief. Fewer than 3 data points → "not enough data yet".
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

from .. import db, notifications
from . import ServiceError
from .evaluation import COMPETENCIES, scorecard

PERIODS = {"3m": "3-month check-in", "6m": "6-month check-in", "12m": "12-month review", "annual": "Annual review"}
REVIEW_COMPETENCIES = ("Domain knowledge", "Technical understanding", "Problem solving", "Communication", "Ownership")


def save_review(employee_id: int, *, period: str, rating: float, competencies: dict, notes: str, actor: dict) -> dict:
    if period not in PERIODS:
        raise ServiceError("Choose a review period.")
    if not 1 <= float(rating) <= 5:
        raise ServiceError("Rating must be between 1 and 5.")
    employee = db.fetch_one("SELECT * FROM employees WHERE id = ?", (employee_id,))
    if not employee:
        raise ServiceError("Employee not found.", 404)
    is_hr = actor["role"] in {"hr", "hr_admin"}
    if not is_hr and employee.get("manager_id") != actor.get("employee_id"):
        raise ServiceError("Only HR or the reporting manager can review this employee.", 403)
    clean = {k: max(1.0, min(5.0, float(v))) for k, v in (competencies or {}).items() if k in REVIEW_COMPETENCIES and v not in (None, "")}
    existing = db.fetch_one("SELECT id FROM performance_reviews WHERE employee_id = ? AND period = ?", (employee_id, period))
    data = {"rating": float(rating), "competencies": clean, "notes": (notes or "").strip()[:3000], "reviewer": actor["user_id"]}
    if existing:
        db.update("performance_reviews", existing["id"], data)
    else:
        db.insert("performance_reviews", {"employee_id": employee_id, "period": period, **data, "created_at": db.now_iso()})
    notifications.notify(employee.get("account_id"), f"{PERIODS[period]} recorded", f"Overall rating {float(rating):g}/5", "/me#/growth")
    db.audit(actor["user_id"], "review_saved", "employee", employee_id, {"period": period, "rating": rating})
    return reviews_for(employee_id)[0]


def reviews_for(employee_id: int) -> list[dict]:
    rows = db.fetch_all("SELECT * FROM performance_reviews WHERE employee_id = ? ORDER BY created_at DESC", (employee_id,))
    for row in rows:
        row["period_label"] = PERIODS.get(row["period"], row["period"])
    return rows


def due_reviews() -> list[dict]:
    """Employees whose 3/6/12-month check-in date has passed without a review."""
    today = date.today()
    due = []
    for e in db.fetch_all("SELECT id, employee_code, full_name, designation, date_of_joining, manager_id FROM employees WHERE status != 'exited'"):
        joined = date.fromisoformat(e["date_of_joining"])
        done = {r["period"] for r in db.fetch_all("SELECT period FROM performance_reviews WHERE employee_id = ?", (e["id"],))}
        for period, months in (("3m", 3), ("6m", 6), ("12m", 12)):
            due_on = joined + timedelta(days=round(30.4 * months))
            if due_on <= today + timedelta(days=14) and period not in done and (today - due_on).days < 120:
                due.append({**e, "period": period, "period_label": PERIODS[period], "due_on": due_on.isoformat()})
    return sorted(due, key=lambda r: r["due_on"])


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def recruitment_intelligence(role_key: str = "") -> dict:
    sql = """SELECT e.id AS employee_id, e.full_name, e.role_key, a.*, AVG(r.rating) AS avg_rating, COUNT(r.id) AS reviews
             FROM employees e JOIN applications a ON a.id = e.application_id
             JOIN performance_reviews r ON r.employee_id = e.id"""
    params: tuple = ()
    if role_key:
        sql += " WHERE e.role_key = ?"
        params = (role_key,)
    sql += " GROUP BY e.id, e.full_name, e.role_key, a.id ORDER BY avg_rating DESC"
    hires = db.fetch_all(sql, params)
    signals: dict[str, list[tuple[float, float]]] = {name: [] for name in ("ATS score", "Mock test", "Interview", *COMPETENCIES)}
    people = []
    for hire in hires:
        app = {**hire, "id": hire["id"]}
        card = scorecard(app)
        rating = float(hire["avg_rating"])
        values = {"ATS score": hire.get("ats_score"), "Mock test": hire.get("test_percent"), "Interview": hire.get("interview_score"),
                  **{c["name"]: c["score"] for c in card["competencies"]}}
        for name, value in values.items():
            if value is not None:
                signals[name].append((float(value), rating))
        people.append({"name": hire["full_name"], "role": hire["role_title"], "rating": round(rating, 2), "reviews": hire["reviews"],
                       "ats": hire.get("ats_score"), "test": hire.get("test_percent"), "interview": hire.get("interview_score")})
    result = []
    for name, pairs in signals.items():
        r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
        strength = None if r is None else "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak"
        result.append({"signal": name, "n": len(pairs), "correlation": r, "strength": strength})
    result.sort(key=lambda x: (x["correlation"] is None, -(abs(x["correlation"] or 0))))
    return {"hires_with_reviews": len(hires), "signals": result, "people": people[:50],
            "note": "Correlations need at least 3 reviewed hires per signal and become meaningful from about 20."}
