"""Open roles (designations) candidates can apply for.

For now the catalogue is a JSON file HR can edit (``catalog/roles.json``); it can move to
a database table with an HR admin screen later without changing the callers.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

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

    def public(self) -> dict:
        data = asdict(self)
        data["skills"] = list(self.skills)
        return data

    def as_job(self) -> dict:
        """The 'job' shape the ported mock-test engine expects."""
        return {"title": self.title, "description": self.description, "additional_skills": list(self.skills)}


@lru_cache(maxsize=1)
def _load() -> dict[str, Role]:
    items = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    roles: dict[str, Role] = {}
    for item in items:
        role = Role(
            key=str(item["key"]),
            title=str(item["title"]),
            department=str(item.get("department", "")),
            location=str(item.get("location", "")),
            experience=str(item.get("experience", "")),
            min_years=float(item.get("min_years", 0)),
            skills=tuple(str(skill) for skill in item.get("skills", [])),
            description=str(item.get("description", "")),
        )
        roles[role.key] = role
    return roles


def all_roles() -> list[Role]:
    return list(_load().values())


def get_role(key: str) -> Role | None:
    return _load().get((key or "").strip())
