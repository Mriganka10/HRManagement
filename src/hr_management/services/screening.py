"""Stage 1 — resume upload and ATS screening against the chosen role.

The ATS engine is the deterministic scorer from Job-Hunting-Agent. Here the job
description comes from the role catalogue (the opening the candidate applied to),
so every candidate for a role is scored against the same requirements.
"""
from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from .. import db, pipeline
from ..engines.ats import score_resume
from ..engines.models import CandidateProfile
from ..engines.resume import parse_resume
from ..roles import Role, get_role
from ..settings import get_settings
from . import Notice, ServiceError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MIN_RESUME_CHARS = 200


def ats_report_dict(report) -> dict:
    data = asdict(report)
    data["score_breakdown"] = [
        {"name": name, "points": points, "max": maximum} for name, points, maximum in report.score_breakdown
    ]
    return data


def score_for_role(resume_path: Path, role: Role, *, experience_years: float, full_name: str, email: str) -> dict:
    try:
        resume = parse_resume(resume_path)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    except Exception as exc:  # unreadable/corrupt file
        raise ServiceError("We could not read this resume. Please upload a text-based PDF or DOCX.") from exc
    if len(resume.text) < MIN_RESUME_CHARS:
        raise ServiceError("We could not extract enough text from this resume. Scanned/image PDFs are not supported yet.")
    profile = CandidateProfile(
        name=full_name,
        email=email,
        target_roles=(role.title,),
        skills=role.skills,
        experience_years=float(experience_years or 0),
        job_description=role.description,
    )
    return ats_report_dict(score_resume(resume, profile))


def submit_application(
    *, email: str, role_key: str, full_name: str, phone: str, experience_years: float,
    filename: str, content: bytes,
) -> tuple[dict, Notice]:
    cfg = get_settings()
    role = get_role(role_key)
    if role is None:
        raise ServiceError("Please choose a valid role.")
    full_name = (full_name or "").strip()[:120]
    if len(full_name) < 2:
        raise ServiceError("Please enter your full name.")
    if not 0 <= float(experience_years) <= 50:
        raise ServiceError("Experience must be between 0 and 50 years.")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ServiceError("Upload a PDF, DOCX, TXT or MD resume.")
    if not content:
        raise ServiceError("The uploaded file is empty.")
    if len(content) > cfg.max_resume_mb * 1024 * 1024:
        raise ServiceError(f"Resume must be {cfg.max_resume_mb} MB or smaller.")
    if db.application_for_role(email, role.key):
        raise ServiceError(f"You have already applied for {role.title}.", 409)

    folder = cfg.upload_dir / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    resume_path = folder / f"resume{suffix}"
    resume_path.write_bytes(content)
    try:
        report = score_for_role(resume_path, role, experience_years=experience_years, full_name=full_name, email=email)
    except ServiceError:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    try:
        application_id = db.create_application(
            email=email, role_key=role.key, role_title=role.title, full_name=full_name, phone=(phone or "").strip()[:30],
            experience_years=float(experience_years), resume_name=Path(filename).name[:200], resume_path=str(resume_path),
            stage=pipeline.SCREENING,
        )
    except Exception as exc:  # unique (email, role) raced by a double submit
        shutil.rmtree(folder, ignore_errors=True)
        raise ServiceError(f"You have already applied for {role.title}.", 409) from exc

    db.add_event(application_id, "applied", actor=email, to_stage=pipeline.SCREENING, detail={"resume": Path(filename).name})
    decision = pipeline.decide_ats(float(report["score"]))
    db.transition_stage(application_id, (pipeline.SCREENING,), decision.next_stage, ats_score=decision.score, ats_report=report)
    db.add_event(
        application_id, "ats_scored", actor="system", from_stage=pipeline.SCREENING, to_stage=decision.next_stage,
        detail={"score": decision.score, "threshold": decision.threshold, "passed": decision.passed},
    )
    notice = Notice(
        kind=decision.email_kind, application_id=application_id, score=decision.score, threshold=decision.threshold,
        next_threshold=get_settings().test_pass_percent if decision.passed else None,
    )
    return db.application(application_id), notice  # type: ignore[return-value]
