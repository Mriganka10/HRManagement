"""Internal talent & skills: skill mapping, internal talent search for a new project or
opening (before hiring externally), skill-gap analysis and training recommendations.

Matching is deterministic and explainable: skills are canonicalised with the same
``canonicalize_skill`` the ATS uses, then each employee is scored on required-skill coverage,
plus small boosts for relevant experience, recent performance and tenure. Employees who
cover ≥ 50% of the required skills are listed as "could be ready with training".
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from .. import db
from ..engines.resume import canonicalize_skill
from ..roles import get_role

TRAINING = {
    "aws": "AWS Cloud Practitioner → AWS Developer Associate", "docker": "Docker fundamentals (hands-on labs)",
    "kubernetes": "Certified Kubernetes Application Developer (CKAD) path", "python": "Advanced Python & testing workshop",
    "sql": "Advanced SQL: window functions and query tuning", "machine learning": "Applied ML course with a capstone project",
    "deep learning": "Deep learning specialisation (CNNs, transformers)", "react": "React + TypeScript component patterns",
    "typescript": "TypeScript for JavaScript developers", "terraform": "Terraform Associate certification path",
    "power bi": "Power BI data modelling and DAX", "tableau": "Tableau desktop specialist", "selenium": "Selenium + pytest automation",
    "nlp": "NLP with transformers (hands-on)", "mlops": "MLOps: MLflow, DVC and CI/CD for models", "fastapi": "Building APIs with FastAPI",
    "communication": "Business communication & presentation skills", "stakeholder management": "Stakeholder management workshop",
}


def _canon(skills) -> list[str]:
    out = []
    for skill in skills or []:
        value = canonicalize_skill(str(skill)).strip()
        if value and value.lower() not in {s.lower() for s in out}:
            out.append(value)
    return out


def training_for(skill: str) -> str:
    return TRAINING.get(skill.lower(), f"Structured learning plan for {skill} (internal mentor + online course)")


def skill_map() -> dict:
    employees = db.fetch_all("SELECT id, full_name, department, skills FROM employees WHERE status != 'exited'")
    counts = Counter()
    by_department: dict[str, Counter] = {}
    for e in employees:
        skills = _canon(e["skills"])
        counts.update(s for s in skills)
        by_department.setdefault(e["department"] or "Unassigned", Counter()).update(skills)
    return {"total_employees": len(employees), "top_skills": [{"skill": s, "employees": n} for s, n in counts.most_common(25)],
            "departments": {d: [{"skill": s, "employees": n} for s, n in c.most_common(8)] for d, c in by_department.items()}}


def search(required: list[str], *, nice_to_have: list[str] | None = None, limit: int = 20) -> dict:
    required = _canon(required)
    nice = _canon(nice_to_have or [])
    if not required:
        return {"required": [], "ready": [], "trainable": []}
    req_lower = [s.lower() for s in required]
    results = []
    for e in db.fetch_all("SELECT * FROM employees WHERE status IN ('active', 'probation')"):
        skills = _canon(e["skills"])
        lower = {s.lower() for s in skills}
        experience_text = " ".join(" ".join([x.get("title", ""), *x.get("highlights", [])]) for x in (e["experience"] or [])).lower()
        matched = [s for s in required if s.lower() in lower or s.lower() in experience_text]
        missing = [s for s in required if s not in matched]
        coverage = len(matched) / len(required)
        nice_hits = [s for s in nice if s.lower() in lower]
        review = db.fetch_one("SELECT AVG(rating) AS r FROM performance_reviews WHERE employee_id = ?", (e["id"],))
        rating = float(review["r"]) if review and review["r"] is not None else None
        tenure_years = (date.today() - date.fromisoformat(e["date_of_joining"])).days / 365
        score = 70 * coverage + 10 * (len(nice_hits) / len(nice) if nice else 0) + (8 * (rating - 3) / 2 if rating else 0) + min(6, tenure_years * 2)
        if coverage == 0:
            continue
        results.append({
            "id": e["id"], "employee_code": e["employee_code"], "name": e["full_name"], "designation": e["designation"],
            "department": e["department"], "coverage": round(coverage * 100), "score": round(score, 1), "matched": matched,
            "missing": missing, "nice_to_have": nice_hits, "rating": round(rating, 1) if rating else None,
            "training": [{"skill": s, "suggestion": training_for(s)} for s in missing],
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"required": required, "ready": [r for r in results if r["coverage"] == 100][:limit],
            "trainable": [r for r in results if 50 <= r["coverage"] < 100][:limit]}


def gap_for_employee(employee: dict, role_key: str = "") -> dict:
    """Skill gap vs the employee's own role (or a target role for career moves)."""
    role = get_role(role_key or employee.get("role_key") or "")
    if role is None:
        role = next((r for r in [get_role(k["key"]) for k in db.fetch_all("SELECT key FROM job_openings")]
                     if r and r.title.lower() == (employee.get("designation") or "").lower()), None)
    have = {s.lower() for s in _canon(employee.get("skills"))}
    if role is None:
        return {"role": None, "have": sorted(have), "missing": [], "recommendations": []}
    required = _canon(role.skills)
    missing = [s for s in required if s.lower() not in have]
    return {"role": role.title, "required": required, "matched": [s for s in required if s.lower() in have], "missing": missing,
            "coverage": round(100 * (len(required) - len(missing)) / len(required)) if required else 100,
            "recommendations": [{"skill": s, "suggestion": training_for(s)} for s in missing]}


def internal_matches(employee: dict) -> list[dict]:
    """Open roles this employee could move into (internal job opportunity matching)."""
    have = {s.lower() for s in _canon(employee.get("skills"))}
    out = []
    for row in db.fetch_all("SELECT key FROM job_openings WHERE status = 'open'"):
        role = get_role(row["key"])
        if not role or role.key == employee.get("role_key"):
            continue
        required = _canon(role.skills)
        matched = [s for s in required if s.lower() in have]
        if required and len(matched) / len(required) >= 0.4:
            out.append({"key": role.key, "title": role.title, "department": role.department, "coverage": round(100 * len(matched) / len(required)),
                        "missing": [s for s in required if s not in matched][:6]})
    return sorted(out, key=lambda r: r["coverage"], reverse=True)[:5]
