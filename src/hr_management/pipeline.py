"""The hiring pipeline: stages, pass/fail rules and which email each outcome sends.

    resume upload
        │  ATS score >= HRM_ATS_PASS_SCORE (75)
        ├── no  → ats_rejected            (email: ats_rejection)
        └── yes → test_pending            (email: test_invite)
                     │ candidate starts → test_in_progress
                     │ percent >= HRM_TEST_PASS_PERCENT (70)
                     ├── no  → test_rejected        (email: test_rejection)
                     └── yes → interview_pending    (email: interview_invite)
                                  │ candidate starts → interview_in_progress
                                  │ score >= HRM_INTERVIEW_PASS_SCORE (75)
                                  ├── no  → interview_rejected  (email: interview_rejection)
                                  └── yes → interview_passed    (email: interview_thanks)

Everything about *rules* lives here; routes only call these functions. Later stages
(HR review, offer, onboarding) are added by extending ``STAGES`` and ``TRANSITIONS``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .settings import get_settings

SCREENING = "screening"
ATS_REJECTED = "ats_rejected"
TEST_PENDING = "test_pending"
TEST_IN_PROGRESS = "test_in_progress"
TEST_REJECTED = "test_rejected"
INTERVIEW_PENDING = "interview_pending"
INTERVIEW_IN_PROGRESS = "interview_in_progress"
INTERVIEW_REJECTED = "interview_rejected"
INTERVIEW_PASSED = "interview_passed"

# Display metadata used by both the candidate and HR screens.
STAGES: dict[str, dict[str, object]] = {
    SCREENING: {"label": "Screening resume", "step": 1, "tone": "active", "final": False},
    ATS_REJECTED: {"label": "Not shortlisted (ATS)", "step": 1, "tone": "rejected", "final": True},
    TEST_PENDING: {"label": "Mock test unlocked", "step": 2, "tone": "action", "final": False},
    TEST_IN_PROGRESS: {"label": "Mock test in progress", "step": 2, "tone": "active", "final": False},
    TEST_REJECTED: {"label": "Not shortlisted (Mock test)", "step": 2, "tone": "rejected", "final": True},
    INTERVIEW_PENDING: {"label": "Interview unlocked", "step": 3, "tone": "action", "final": False},
    INTERVIEW_IN_PROGRESS: {"label": "Interview in progress", "step": 3, "tone": "active", "final": False},
    INTERVIEW_REJECTED: {"label": "Not selected (Interview)", "step": 3, "tone": "rejected", "final": True},
    INTERVIEW_PASSED: {"label": "Interview cleared – next steps soon", "step": 4, "tone": "passed", "final": True},
}

# Allowed moves. Anything else is refused by ``db.transition_stage``.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCREENING: (ATS_REJECTED, TEST_PENDING),
    TEST_PENDING: (TEST_IN_PROGRESS,),
    TEST_IN_PROGRESS: (TEST_REJECTED, INTERVIEW_PENDING),
    INTERVIEW_PENDING: (INTERVIEW_IN_PROGRESS,),
    INTERVIEW_IN_PROGRESS: (INTERVIEW_REJECTED, INTERVIEW_PASSED),
}

# Which email goes out when an application lands in a stage.
STAGE_EMAILS: dict[str, str] = {
    ATS_REJECTED: "ats_rejection",
    TEST_PENDING: "test_invite",
    TEST_REJECTED: "test_rejection",
    INTERVIEW_PENDING: "interview_invite",
    INTERVIEW_REJECTED: "interview_rejection",
    INTERVIEW_PASSED: "interview_thanks",
}


@dataclass(frozen=True)
class Decision:
    passed: bool
    score: float
    threshold: float
    next_stage: str
    email_kind: str


def can_move(from_stage: str, to_stage: str) -> bool:
    return to_stage in TRANSITIONS.get(from_stage, ())


def _decide(score: float, threshold: float, pass_stage: str, fail_stage: str) -> Decision:
    passed = float(score) >= float(threshold)
    stage = pass_stage if passed else fail_stage
    return Decision(passed=passed, score=round(float(score), 2), threshold=float(threshold), next_stage=stage, email_kind=STAGE_EMAILS[stage])


def decide_ats(score: float) -> Decision:
    return _decide(score, get_settings().ats_pass_score, TEST_PENDING, ATS_REJECTED)


def decide_test(percent: float) -> Decision:
    return _decide(percent, get_settings().test_pass_percent, INTERVIEW_PENDING, TEST_REJECTED)


def decide_interview(score: float) -> Decision:
    return _decide(score, get_settings().interview_pass_score, INTERVIEW_PASSED, INTERVIEW_REJECTED)


def thresholds() -> dict[str, float]:
    cfg = get_settings()
    return {"ats": cfg.ats_pass_score, "test": cfg.test_pass_percent, "interview": cfg.interview_pass_score}


def stage_view(stage: str) -> dict[str, object]:
    meta = STAGES.get(stage, {"label": stage, "step": 0, "tone": "active", "final": False})
    return {"key": stage, **meta}
