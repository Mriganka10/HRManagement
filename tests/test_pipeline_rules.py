"""Pass/fail rules and allowed stage moves."""
from hr_management import pipeline


def test_thresholds_are_inclusive():
    assert pipeline.decide_ats(75).passed and not pipeline.decide_ats(74.9).passed
    assert pipeline.decide_test(70).passed and not pipeline.decide_test(69.9).passed
    assert pipeline.decide_interview(75).passed and not pipeline.decide_interview(74).passed


def test_each_outcome_sends_the_right_email():
    assert pipeline.decide_ats(80).email_kind == "test_invite"
    assert pipeline.decide_ats(50).email_kind == "ats_rejection"
    assert pipeline.decide_test(90).email_kind == "interview_invite"
    assert pipeline.decide_test(10).email_kind == "test_rejection"
    assert pipeline.decide_interview(80).email_kind == "selected"  # HRM_AUTO_SELECT=true (default)
    assert pipeline.decide_interview(20).email_kind == "interview_rejection"


def test_manual_selection_mode(monkeypatch):
    from hr_management import settings

    monkeypatch.setenv("HRM_AUTO_SELECT", "false")
    settings.reload_settings()
    decision = pipeline.decide_interview(80)
    assert decision.next_stage == pipeline.INTERVIEW_PASSED and decision.email_kind == "interview_thanks"


def test_thresholds_come_from_environment(monkeypatch):
    from hr_management import settings

    monkeypatch.setenv("HRM_ATS_PASS_SCORE", "60")
    settings.reload_settings()
    assert pipeline.decide_ats(65).passed


def test_stages_cannot_be_skipped():
    assert pipeline.can_move(pipeline.TEST_PENDING, pipeline.TEST_IN_PROGRESS)
    assert not pipeline.can_move(pipeline.ATS_REJECTED, pipeline.TEST_PENDING)
    assert not pipeline.can_move(pipeline.TEST_PENDING, pipeline.INTERVIEW_PENDING)
    assert pipeline.can_move(pipeline.SELECTED, pipeline.HIRED)
    assert not pipeline.can_move(pipeline.TEST_PENDING, pipeline.HIRED)
