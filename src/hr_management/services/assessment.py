"""Stage 2 — role-based mock test (timed MCQ), using the Job-Hunting-Agent test engine.

Integrity rules:
- The answer key never leaves the server (``public_questions`` strips it), and the
  candidate never sees correct answers afterwards, so the question bank stays usable.
- Time is measured on the server from ``started_at``. Answers are autosaved; after the
  deadline (+ grace) only the autosaved answers count and the test is finalised on the
  next request, even if the candidate never presses Submit.
- One test per application; stage changes are compare-and-set.
"""
from __future__ import annotations

import secrets
from typing import Any

from .. import db, pipeline
from ..engines.llm_client import enabled as llm_enabled
from ..engines.mock_test import build_mock_test, grade_mock_test, public_questions
from ..roles import get_role
from ..settings import get_settings
from . import Notice, ServiceError


def _elapsed(test: dict) -> float:
    started = db.parse_time(test.get("started_at"))
    return (db.utcnow() - started).total_seconds() if started else 0.0


def _deadline_passed(test: dict) -> bool:
    return _elapsed(test) > int(test["time_limit_seconds"]) + get_settings().test_grace_seconds


def _clean_answers(answers: Any, questions: list[dict]) -> dict[str, int | None]:
    valid = {str(item["id"]) for item in questions}
    cleaned: dict[str, int | None] = {}
    if isinstance(answers, dict):
        for key, value in answers.items():
            if str(key) in valid:
                try:
                    cleaned[str(key)] = int(value) if value is not None and 0 <= int(value) <= 3 else None
                except (TypeError, ValueError):
                    cleaned[str(key)] = None
    return cleaned


def _clean_integrity(raw: Any, previous: dict | None = None) -> dict[str, int]:
    previous = previous or {}
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("tab_switches", "fullscreen_exits", "copy_attempts"):
        try:
            value = max(0, min(10_000, int(raw.get(key, 0))))
        except (TypeError, ValueError):
            value = 0
        out[key] = max(value, int(previous.get(key, 0) or 0))  # counters only go up
    return out


def public_test(test: dict) -> dict:
    data = {
        "test_id": test["id"],
        "status": test["status"],
        "topics": test.get("topics") or [],
        "time_limit_seconds": int(test["time_limit_seconds"]),
        "questions": public_questions(test.get("questions") or []),
        "answers": test.get("answers") or {},
    }
    if test["status"] == "in_progress":
        data["remaining_seconds"] = max(0, int(int(test["time_limit_seconds"]) - _elapsed(test)))
    return data


def start_test(app: dict) -> dict:
    """Create the test on first call; later calls resume the same test."""
    if app["stage"] == pipeline.TEST_PENDING:
        if not db.transition_stage(app["id"], (pipeline.TEST_PENDING,), pipeline.TEST_IN_PROGRESS):
            app = db.application(app["id"]) or app
        else:
            db.add_event(app["id"], "test_started", actor=app["email"], from_stage=pipeline.TEST_PENDING, to_stage=pipeline.TEST_IN_PROGRESS)
    elif app["stage"] != pipeline.TEST_IN_PROGRESS:
        raise ServiceError("The mock test is not available for this application.", 409)

    test = db.mock_test_for_application(app["id"])
    if test is None:
        role = get_role(app["role_key"])
        if role is None:
            raise ServiceError("This role is no longer open.", 410)
        cfg = get_settings()
        built = build_mock_test(
            role.as_job(),
            {"target_roles": role.title, "skills": ", ".join(role.skills), "experience_years": app.get("experience_years") or 0},
            length=cfg.test_length,
            difficulty=cfg.test_difficulty,
            seed=secrets.token_hex(8),
            allow_llm=llm_enabled(("HRM_MOCK_TEST_LLM_API_KEY", "HRM_LLM_API_KEY")),
        )
        try:
            db.create_mock_test(
                application_id=app["id"], email=app["email"], questions=built["questions"],
                topics=built["topics"], time_limit_seconds=built["time_limit_seconds"],
            )
        except Exception:  # another tab created it first (UNIQUE application_id)
            pass
        test = db.mock_test_for_application(app["id"])
    if test and test["status"] == "in_progress" and _deadline_passed(test):
        finalize_test(app, test, None, None)
        raise ServiceError("Time is up for this test. Your autosaved answers were submitted.", 409)
    return public_test(test)  # type: ignore[arg-type]


def autosave(app: dict, answers: Any, integrity: Any) -> dict:
    test = db.mock_test_for_application(app["id"])
    if not test or test["status"] != "in_progress":
        raise ServiceError("No running test to save.", 409)
    if _deadline_passed(test):
        return {"saved": False, "expired": True}
    merged = {**(test.get("answers") or {}), **_clean_answers(answers, test["questions"])}
    db.save_test_answers(test["id"], merged, _clean_integrity(integrity, test.get("integrity")))
    return {"saved": True, "remaining_seconds": max(0, int(int(test["time_limit_seconds"]) - _elapsed(test)))}


def submit(app: dict, answers: Any, integrity: Any) -> tuple[dict, Notice | None]:
    test = db.mock_test_for_application(app["id"])
    if not test:
        raise ServiceError("Start the test first.", 409)
    if test["status"] == "completed":
        return test.get("scorecard") or {}, None
    return finalize_test(app, test, answers, integrity)


def finalize_test(app: dict, test: dict, answers: Any, integrity: Any) -> tuple[dict, Notice | None]:
    saved = test.get("answers") or {}
    late = _deadline_passed(test)
    # After the deadline only the autosaved answers count.
    final_answers = saved if late else {**saved, **_clean_answers(answers, test["questions"])}
    integrity_data = {**_clean_integrity(integrity, test.get("integrity")), "late_submission": late}
    scorecard = grade_mock_test(
        test["questions"], final_answers,
        elapsed_seconds=_elapsed(test), time_limit_seconds=int(test["time_limit_seconds"]),
        job={"title": app["role_title"]},
    )
    percent = float(scorecard.get("percent") or 0)
    if not db.complete_mock_test(test["id"], answers=final_answers, scorecard=scorecard, percent=percent, integrity=integrity_data):
        fresh = db.mock_test_for_application(app["id"]) or {}
        return fresh.get("scorecard") or scorecard, None  # already graded by a parallel request

    decision = pipeline.decide_test(percent)
    db.transition_stage(app["id"], (pipeline.TEST_IN_PROGRESS,), decision.next_stage, test_percent=decision.score)
    db.add_event(
        app["id"], "test_graded", actor="system", from_stage=pipeline.TEST_IN_PROGRESS, to_stage=decision.next_stage,
        detail={"percent": decision.score, "threshold": decision.threshold, "passed": decision.passed, **integrity_data},
    )
    notice = Notice(
        kind=decision.email_kind, application_id=app["id"], score=decision.score, threshold=decision.threshold,
        next_threshold=get_settings().interview_pass_score if decision.passed else None,
    )
    return scorecard, notice


def finalize_if_expired(app: dict) -> Notice | None:
    """Called when a candidate opens the app: closes tests whose time ran out."""
    if app["stage"] != pipeline.TEST_IN_PROGRESS:
        return None
    test = db.mock_test_for_application(app["id"])
    if test and test["status"] == "in_progress" and _deadline_passed(test):
        return finalize_test(app, test, None, None)[1]
    return None


def candidate_summary(scorecard: dict) -> dict:
    """What the candidate sees: scores and topic strengths, never the answer key."""
    return {
        key: scorecard.get(key)
        for key in ("percent", "correct", "incorrect", "unanswered", "total", "grade", "topic_breakdown", "difficulty_breakdown", "strengths", "weak_areas", "time")
    }
