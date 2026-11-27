"""Job openings (roles / designations) candidates can apply for.

Stored in the ``job_openings`` table and managed by HR in the portal. On the very first
start the table is seeded from ``catalog/roles.json``. Callers keep using ``get_role`` /
``all_roles`` exactly as in v1.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import db

CATALOG_PATH = Path(__file__).resolve().parent / "catalog" / "roles.json"


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    department: str
    location: str
    experience: str
    min_years: float
    skills: tuple[str, ...]
    description: str
    employment_type: str = "Full-time"
    openings: int = 1
    annual_ctc: float = 0
    status: str = "open"
    id: int = 0

    def public(self) -> dict:
        data = asdict(self)
        data["skills"] = list(self.skills)
        data.pop("annual_ctc", None)  # salary bands are HR-only
        return data

    def as_job(self) -> dict:
        """The 'job' shape the ported mock-test engine expects."""
        return {"title": self.title, "description": self.description, "additional_skills": list(self.skills)}


def _from_row(row: dict) -> Role:
    return Role(
        id=int(row["id"]), key=row["key"], title=row["title"], department=row["department"], location=row["location"],
        experience=row["experience"], min_years=float(row["min_years"] or 0), skills=tuple(row["skills"] or ()),
        description=row["description"], employment_type=row["employment_type"], openings=int(row["openings"] or 1),
        annual_ctc=float(row["annual_ctc"] or 0), status=row["status"],
    )


def compose_description(summary: str, responsibilities: str, skills: list[str], min_years: float) -> str:
    """Job descriptions in the shape the ATS requirement parser reads cleanly."""
    parts = [summary.strip()]
    if responsibilities.strip():
        parts.append(f"Responsibilities: {responsibilities.strip().rstrip('.')}.")
    parts.append(f"Required skills: {', '.join(skills)}.")
    parts.append(f"Experience: {int(min_years)}+ years in a similar role.")
    return "\n".join(parts)


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "role"


def seed_from_catalog() -> None:
    if db.fetch_one("SELECT id FROM job_openings LIMIT 1"):
        return
    for item in json.loads(CATALOG_PATH.read_text(encoding="utf-8")):
        stamp = db.now_iso()
        db.insert("job_openings", {
            "key": item["key"], "title": item["title"], "department": item.get("department", ""),
            "location": item.get("location", ""), "employment_type": item.get("employment_type", "Full-time"),
            "experience": item.get("experience", ""), "min_years": float(item.get("min_years", 0)),
            "skills": list(item.get("skills", [])), "description": item.get("description", ""),
            "openings": int(item.get("openings", 2)), "annual_ctc": float(item.get("annual_ctc", 0)),
            "status": "open", "created_at": stamp, "updated_at": stamp,
        })


def all_roles(*, include_closed: bool = False) -> list[Role]:
    sql = "SELECT * FROM job_openings" + ("" if include_closed else " WHERE status = 'open'") + " ORDER BY department, title"
    return [_from_row(row) for row in db.fetch_all(sql)]


def get_role(key: str) -> Role | None:
    row = db.fetch_one("SELECT * FROM job_openings WHERE key = ?", ((key or "").strip(),))
    return _from_row(row) if row else None
