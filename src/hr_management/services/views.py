"""How applications are shown to candidates and to HR (what each audience may see)."""
from __future__ import annotations

from .. import db, pipeline
from ..roles import get_role
from . import assessment, interview


def _ats_summary(report: dict | None) -> dict | None:
    if not report:
        return None
    return {
        key: report.get(key)
        for key in ("score", "score_breakdown", "strengths", "improvements", "matched_keywords", "missing_keywords",
                    "role_profile", "confidence_label", "score_range")
    }


def candidate_application(app: dict) -> dict:
    test = db.mock_test_for_application(app["id"])
    iv = db.interview_for_application(app["id"])
    role = get_role(app["role_key"])
    return {
        "id": app["id"],
        "role": role.public() if role else {"key": app["role_key"], "title": app["role_title"]},
        "role_title": app["role_title"],
        "full_name": app["full_name"],
        "stage": pipeline.stage_view(app["stage"]),
        "thresholds": pipeline.thresholds(),
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "resume_name": app["resume_name"],
        "ats": _ats_summary(app.get("ats_report")),
        "test": (
            {"status": test["status"], "percent": test.get("percent"),
             "summary": assessment.candidate_summary(test.get("scorecard") or {}) if test["status"] == "completed" else None}
            if test else None
        ),
        "interview": (
            {"status": iv["status"], "score": iv.get("score"),
             "summary": interview.candidate_summary(iv.get("report") or {}) if iv["status"] == "completed" else None}
            if iv else None
        ),
    }


def hr_row(app: dict) -> dict:
    return {
        "id": app["id"],
        "email": app["email"],
        "full_name": app["full_name"],
        "phone": app["phone"],
        "role_key": app["role_key"],
        "role_title": app["role_title"],
        "experience_years": app["experience_years"],
        "stage": pipeline.stage_view(app["stage"]),
        "ats_score": app.get("ats_score"),
        "test_percent": app.get("test_percent"),
        "interview_score": app.get("interview_score"),
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
    }


def hr_detail(app: dict) -> dict:
    test = db.mock_test_for_application(app["id"]) or {}
    iv = db.interview_for_application(app["id"]) or {}
    questions = {str(q["id"]): q for q in iv.get("questions") or []}
    transcript = [
        {"question": questions.get(qid, {}).get("question", ""), "category": questions.get(qid, {}).get("category", ""),
         "answer_type": answer.get("answer_type"), "answer": answer.get("answer", "")}
        for qid, answer in (iv.get("answers") or {}).items()
    ]
    return {
        **hr_row(app),
        "resume_name": app["resume_name"],
        "ats_report": app.get("ats_report"),
        "test": {
            "status": test.get("status"), "percent": test.get("percent"), "started_at": test.get("started_at"),
            "completed_at": test.get("completed_at"), "integrity": test.get("integrity"),
            "scorecard": {k: v for k, v in (test.get("scorecard") or {}).items() if k != "review"},
        } if test else None,
        "interview": {
            "status": iv.get("status"), "score": iv.get("score"), "started_at": iv.get("started_at"),
            "completed_at": iv.get("completed_at"), "integrity": iv.get("integrity"),
            "report": {k: v for k, v in (iv.get("report") or {}).items() if k != "answers"}, "transcript": transcript,
        } if iv else None,
        "events": db.events_for_application(app["id"]),
        "emails": db.emails(app["id"]),
    }
