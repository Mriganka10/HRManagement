"""Stage 3 — role-based mock interview, using the Job-Hunting-Agent interview engines.

- Questions come from ``build_question_groups`` for the applied role and its skills, at
  the candidate's level (from years of experience). Technical roles get coding problems.
- Answers are typed or dictated in the browser and autosaved after every question.
- Scoring is the evidence-based evaluator (communication, technical accuracy, confidence,
  problem solving); an LLM review is blended in only when an API key is configured.
- Code is never executed on the server and browser-reported test results are ignored,
  because a candidate could fake them.
"""
from __future__ import annotations

import copy
import secrets
from typing import Any

from .. import db, pipeline
from ..engines.interview_coding import add_coding_questions
from ..engines.interview_evaluator import evaluate_interview
from ..engines.interview_questions import build_question_groups, interview_level, select_question_sequence
from ..roles import get_role
from ..settings import get_settings
from . import Notice, ServiceError

MODE_LIMITS = {"quick": 5, "standard": 8, "deep": 10}
MAX_ANSWER_CHARS = 8000


def _public_questions(questions: list[dict]) -> list[dict]:
    """Strip hidden coding test cases before sending questions to the browser."""
    public = []
    for item in questions:
        item = copy.deepcopy(item)
        item.pop("previously_asked", None)
        coding = item.get("coding")
        if isinstance(coding, dict):
            coding.pop("tests", None)
        public.append(item)
    return public


def _clean_integrity(raw: Any, previous: dict | None = None) -> dict[str, int]:
    previous = previous or {}
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("tab_switches", "paste_events"):
        try:
            value = max(0, min(10_000, int(raw.get(key, 0))))
        except (TypeError, ValueError):
            value = 0
        out[key] = max(value, int(previous.get(key, 0) or 0))
    return out


def public_interview(interview: dict) -> dict:
    return {
        "interview_id": interview["id"],
        "status": interview["status"],
        "questions": _public_questions(interview.get("questions") or []),
        "answers": interview.get("answers") or {},
    }


def build_questions(app: dict) -> list[dict]:
    role = get_role(app["role_key"])
    if role is None:
        raise ServiceError("This role is no longer open.", 410)
    mode = get_settings().interview_mode if get_settings().interview_mode in MODE_LIMITS else "standard"
    roles, skills = (role.title,), tuple(role.skills)
    level = interview_level(float(app.get("experience_years") or 0), role.title)
    groups = build_question_groups(roles, skills, level)
    questions = select_question_sequence(groups, MODE_LIMITS[mode], mode, seed=secrets.token_hex(8))
    return add_coding_questions(
        questions, roles=roles, skills=skills, level=level, mode=mode, previous_questions=[], seed=secrets.token_hex(8),
    )


def start(app: dict) -> dict:
    if app["stage"] == pipeline.INTERVIEW_PENDING:
        if db.transition_stage(app["id"], (pipeline.INTERVIEW_PENDING,), pipeline.INTERVIEW_IN_PROGRESS):
            db.add_event(app["id"], "interview_started", actor=app["email"], from_stage=pipeline.INTERVIEW_PENDING,
                         to_stage=pipeline.INTERVIEW_IN_PROGRESS)
    elif app["stage"] != pipeline.INTERVIEW_IN_PROGRESS:
        raise ServiceError("The interview is not available for this application.", 409)
    interview = db.interview_for_application(app["id"])
    if interview is None:
        try:
            db.create_interview(application_id=app["id"], email=app["email"], questions=build_questions(app))
        except ServiceError:
            raise
        except Exception:  # created by a parallel request (UNIQUE application_id)
            pass
        interview = db.interview_for_application(app["id"])
    return public_interview(interview)  # type: ignore[arg-type]


def _clean_answers(raw: Any, questions: list[dict]) -> dict[str, dict]:
    by_id = {str(item["id"]): item for item in questions}
    cleaned: dict[str, dict] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            question = by_id.get(str(key))
            if question is None:
                continue
            text = value.get("answer") if isinstance(value, dict) else value
            cleaned[str(key)] = {
                "question_id": str(key),
                "answer": str(text or "")[:MAX_ANSWER_CHARS],
                "answer_type": "code" if question.get("answer_mode") == "code" else "text",
                "code_language": str(question.get("editor_language") or ""),
            }
    return cleaned


def autosave(app: dict, answers: Any, integrity: Any) -> dict:
    interview = db.interview_for_application(app["id"])
    if not interview or interview["status"] != "in_progress":
        raise ServiceError("No running interview to save.", 409)
    merged = {**(interview.get("answers") or {}), **_clean_answers(answers, interview["questions"])}
    db.save_interview_answers(interview["id"], merged, _clean_integrity(integrity, interview.get("integrity")))
    return {"saved": True, "answered": sum(1 for item in merged.values() if item.get("answer", "").strip())}


def complete(app: dict, answers: Any, integrity: Any) -> tuple[dict, Notice | None]:
    interview = db.interview_for_application(app["id"])
    if not interview:
        raise ServiceError("Start the interview first.", 409)
    if interview["status"] == "completed":
        return interview.get("report") or {}, None
    role = get_role(app["role_key"])
    questions = interview["questions"]
    merged = {**(interview.get("answers") or {}), **_clean_answers(answers, questions)}
    integrity_data = _clean_integrity(integrity, interview.get("integrity"))
    mode = get_settings().interview_mode if get_settings().interview_mode in MODE_LIMITS else "standard"
    report = evaluate_interview(
        list(merged.values()), questions,
        roles=(app["role_title"],), skills=tuple(role.skills) if role else (), interview_mode=mode,
    )
    score = float(report.get("score") or 0)
    if not db.complete_interview(interview["id"], answers=merged, report=report, score=score, integrity=integrity_data):
        fresh = db.interview_for_application(app["id"]) or {}
        return fresh.get("report") or report, None
    decision = pipeline.decide_interview(score)
    db.transition_stage(app["id"], (pipeline.INTERVIEW_IN_PROGRESS,), decision.next_stage, interview_score=decision.score)
    db.add_event(
        app["id"], "interview_scored", actor="system", from_stage=pipeline.INTERVIEW_IN_PROGRESS, to_stage=decision.next_stage,
        detail={"score": decision.score, "threshold": decision.threshold, "passed": decision.passed, **integrity_data},
    )
    return report, Notice(kind=decision.email_kind, application_id=app["id"], score=decision.score, threshold=decision.threshold)


def candidate_summary(report: dict) -> dict:
    return {
        key: report.get(key)
        for key in ("score", "summary", "strengths", "improvements", "improvement_areas", "rubric", "answered", "question_count")
    }
