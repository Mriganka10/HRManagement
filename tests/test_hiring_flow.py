"""End-to-end recruitment: apply → ATS → mock test → interview → selection → onboarding → employee login."""
import re

from conftest import apply, staff_client
from hr_management import db, pipeline

GOOD = ("In my last role I designed a FastAPI service with PostgreSQL and Redis. First I measured the p95 latency, then I added "
        "indexes and caching, and validated the change with load tests. The result was a 45% faster API and fewer incidents. "
        "I would apply the same approach here: clarify the requirement, compare trade-offs, test, and monitor.")

ONBOARDING = {
    "full_name": "Rahul Verma", "phone": "+91 98300 12345", "date_of_birth": "1998-04-12", "gender": "Male", "blood_group": "O+",
    "address": "Salt Lake, Kolkata", "emergency_contact_name": "Sunita Verma", "emergency_contact_relation": "Mother",
    "emergency_contact_phone": "+91 98300 54321", "pan_number": "abcde1234f", "bank_account_name": "Rahul Verma",
    "bank_account_number": "123456789012", "bank_ifsc": "hdfc0001234", "skills": ["Python", "FastAPI"],
}


def _kinds(app_id: int) -> list[str]:
    return [row["kind"] for row in reversed(db.emails(app_id))]


def _pass_test(client, app_id: int) -> dict:
    test = client.post(f"/api/applications/{app_id}/test/start").json()["test"]
    stored = db.mock_test_for_application(app_id)
    assert all("answer_index" not in q for q in test["questions"])  # answer key never sent to the browser
    key = {q["id"]: q["answer_index"] for q in stored["questions"]}
    return client.post(f"/api/applications/{app_id}/test/submit", json={"answers": key, "integrity": {"tab_switches": 1}}).json()


def test_full_journey_to_employee(candidate_client, hr_client, app, monkeypatch):
    client = candidate_client("rahul@example.com")
    response = apply(client, "strong_resume_backend_developer.txt")
    assert response.status_code == 200, response.text
    application = response.json()["application"]
    assert application["ats"]["score"] >= 75 and application["stage"]["key"] == pipeline.TEST_PENDING
    app_id = application["id"]
    assert apply(client, "strong_resume_backend_developer.txt").status_code == 409  # one application per role

    assert _pass_test(client, app_id)["application"]["stage"]["key"] == pipeline.INTERVIEW_PENDING
    iv = client.post(f"/api/applications/{app_id}/interview/start").json()["interview"]
    assert all("tests" not in (q.get("coding") or {}) for q in iv["questions"])  # hidden test cases stay server-side
    from hr_management.services import interview as interview_service

    original = interview_service.evaluate_interview
    monkeypatch.setattr(interview_service, "evaluate_interview", lambda *a, **k: {**original(*a, **k), "score": 82.0})
    answers = {q["id"]: GOOD for q in iv["questions"]}
    done = client.post(f"/api/applications/{app_id}/interview/complete", json={"answers": answers}).json()["application"]
    assert done["stage"]["key"] == pipeline.SELECTED  # HRM_AUTO_SELECT=true

    form = client.get(f"/api/applications/{app_id}/onboarding").json()
    assert "Python" in form["form"]["skills"] and form["form"]["education"]  # prefilled from the resume
    assert "skills" in form["prefilled_fields"] and form["offer"]["designation"] == "Backend Developer"

    bad = client.post(f"/api/applications/{app_id}/onboarding/submit", json={"form": {**ONBOARDING, "pan_number": "123"}, "confirmed": True})
    assert bad.status_code == 422 and "PAN" in bad.json()["detail"]
    result = client.post(f"/api/applications/{app_id}/onboarding/submit", json={"form": ONBOARDING, "confirmed": True}).json()
    assert re.fullmatch(r"KZE\d{4}", result["employee_code"]) and result["application"]["stage"]["key"] == pipeline.HIRED
    assert client.post(f"/api/applications/{app_id}/onboarding/submit", json={"form": ONBOARDING, "confirmed": True}).status_code == 409
    assert _kinds(app_id) == ["test_invite", "interview_invite", "selected", "welcome_credentials"]

    # Credentials from the welcome email work; the temporary password must be changed first.
    from hr_management.settings import get_settings

    outbox = sorted((get_settings().outbox_dir).glob("*welcome_credentials*"))[-1].read_text()
    password = re.search(r"Temporary password</td><td[^>]*>([A-Za-z0-9]{12})<", outbox).group(1)
    employee = staff_client(app, result["user_id"], password)
    assert employee.get("/api/me/home").status_code == 403  # password change required
    employee = staff_client(app, result["user_id"], password, change_to="NewPassw0rd99")
    home = employee.get("/api/me/home").json()
    assert home["profile"]["employee_code"] == result["employee_code"] and home["profile"]["pan_number"].endswith("234F")
    assert "•" in home["profile"]["pan_number"]  # masked unless revealed

    detail = hr_client.get(f"/api/hr/recruitment/applications/{app_id}").json()["application"]
    assert detail["evaluation"]["scorecard"]["competencies"] and detail["evaluation"]["swot"]["strengths"]
    assert hr_client.get(f"/api/hr/recruitment/applications/{app_id}/resume").status_code == 200


def test_manual_selection_when_auto_select_off(candidate_client, hr_client, monkeypatch):
    from hr_management import settings
    from hr_management.services import interview as interview_service

    monkeypatch.setenv("HRM_AUTO_SELECT", "false")
    settings.reload_settings()
    client = candidate_client("asha@example.com")
    app_id = apply(client, "strong_resume_backend_developer.txt").json()["application"]["id"]
    _pass_test(client, app_id)
    iv = client.post(f"/api/applications/{app_id}/interview/start").json()["interview"]
    original = interview_service.evaluate_interview
    monkeypatch.setattr(interview_service, "evaluate_interview", lambda *a, **k: {**original(*a, **k), "score": 90.0})
    done = client.post(f"/api/applications/{app_id}/interview/complete", json={"answers": {q["id"]: GOOD for q in iv["questions"]}}).json()
    assert done["application"]["stage"]["key"] == pipeline.INTERVIEW_PASSED
    assert client.get(f"/api/applications/{app_id}/onboarding").status_code == 409
    r = hr_client.post(f"/api/hr/recruitment/applications/{app_id}/decision", json={"select": True})
    assert r.status_code == 200 and r.json()["application"]["stage"]["key"] == pipeline.SELECTED
    assert client.get(f"/api/applications/{app_id}/onboarding").status_code == 200
    assert _kinds(app_id)[-2:] == ["interview_thanks", "selected"]


def test_rejection_paths(candidate_client):
    weak = candidate_client("amit@example.com")
    app = apply(weak, "weak_resume.txt", years=0).json()["application"]
    assert app["stage"]["key"] == pipeline.ATS_REJECTED and _kinds(app["id"]) == ["ats_rejection"]
    assert weak.post(f"/api/applications/{app['id']}/test/start").status_code == 409

    client = candidate_client("rahul2@example.com")
    app_id = apply(client, "strong_resume_backend_developer.txt").json()["application"]["id"]
    client.post(f"/api/applications/{app_id}/test/start")
    result = client.post(f"/api/applications/{app_id}/test/submit", json={"answers": {}}).json()["application"]
    assert result["stage"]["key"] == pipeline.TEST_REJECTED
    client.post(f"/api/applications/{app_id}/test/submit", json={"answers": {}})  # resubmit changes nothing
    assert _kinds(app_id) == ["test_invite", "test_rejection"]


def test_expired_test_uses_autosaved_answers(candidate_client):
    client = candidate_client("late@example.com")
    app_id = apply(client, "strong_resume_backend_developer.txt").json()["application"]["id"]
    client.post(f"/api/applications/{app_id}/test/start")
    key = {q["id"]: q["answer_index"] for q in db.mock_test_for_application(app_id)["questions"]}
    client.post(f"/api/applications/{app_id}/test/autosave", json={"answers": key})
    db.execute("UPDATE mock_tests SET started_at = '2020-01-01T00:00:00+00:00' WHERE application_id = ?", (app_id,))
    app = client.get(f"/api/applications/{app_id}").json()["application"]
    assert app["stage"]["key"] == pipeline.INTERVIEW_PENDING and app["test"]["percent"] == 100


def test_isolation_between_users_and_portals(candidate_client, hr_client):
    owner = candidate_client("owner@example.com")
    app_id = apply(owner, "strong_resume_backend_developer.txt").json()["application"]["id"]
    intruder = candidate_client("intruder@example.com")
    assert intruder.get(f"/api/applications/{app_id}").status_code == 404
    assert owner.get("/api/hr/dashboard").status_code == 401  # candidates are not staff
    assert hr_client.get("/api/applications").status_code == 401  # staff are not candidates
