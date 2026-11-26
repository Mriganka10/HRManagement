"""End-to-end: login → resume → ATS → mock test → interview → emails, plus the rejection paths."""
from hr_management import db, pipeline
from conftest import HR_EMAIL, apply


def _kinds(app_id: int) -> list[str]:
    return [row["kind"] for row in reversed(db.emails(app_id))]


def _pass_test(client, app_id: int) -> dict:
    test = client.post(f"/api/applications/{app_id}/test/start").json()["test"]
    stored = db.mock_test_for_application(app_id)
    key = {q["id"]: q["answer_index"] for q in stored["questions"]}
    assert all("answer_index" not in q for q in test["questions"])  # key never sent to the browser
    return client.post(f"/api/applications/{app_id}/test/submit", json={"answers": key, "integrity": {"tab_switches": 1}}).json()


def test_login_requires_valid_code(make_client):
    from fastapi.testclient import TestClient
    from hr_management.web import create_app

    client = TestClient(create_app())
    client.post("/api/auth/request-otp", json={"email": "a@example.com"})
    assert client.post("/api/auth/verify", json={"email": "a@example.com", "otp": "000000"}).status_code == 400
    assert client.get("/api/applications").status_code == 401


def test_full_successful_journey(make_client):
    client = make_client("rahul@example.com")
    response = apply(client, "strong_resume_backend_developer.txt")
    assert response.status_code == 200, response.text
    app = response.json()["application"]
    assert app["ats"]["score"] >= 75 and app["stage"]["key"] == pipeline.TEST_PENDING
    app_id = app["id"]

    # duplicate application for the same role is refused
    assert apply(client, "strong_resume_backend_developer.txt").status_code == 409

    result = _pass_test(client, app_id)
    assert result["application"]["stage"]["key"] == pipeline.INTERVIEW_PENDING
    assert result["application"]["test"]["percent"] == 100

    iv = client.post(f"/api/applications/{app_id}/interview/start").json()["interview"]
    assert iv["questions"] and all("tests" not in (q.get("coding") or {}) for q in iv["questions"])
    good = ("In my last role I designed a FastAPI service with PostgreSQL and Redis. First I measured the p95 latency, "
            "then I added indexes and caching, and validated the change with load tests. The result was a 45% faster API "
            "and fewer incidents. I would apply the same approach here: clarify the requirement, compare trade-offs, test, and monitor.")
    answers = {q["id"]: (q.get("coding", {}).get("starter_code", "") + "\n    return sorted(nums)\n# O(n log n) time, O(n) space"
                         if q["answer_mode"] == "code" else good) for q in iv["questions"]}
    first = next(iter(answers))
    assert client.post(f"/api/applications/{app_id}/interview/autosave", json={"answers": {first: answers[first]}}).json()["saved"]
    done = client.post(f"/api/applications/{app_id}/interview/complete", json={"answers": answers}).json()["application"]
    assert done["stage"]["key"] in {pipeline.INTERVIEW_PASSED, pipeline.INTERVIEW_REJECTED}
    assert done["interview"]["score"] is not None
    expected_last = "interview_thanks" if done["stage"]["key"] == pipeline.INTERVIEW_PASSED else "interview_rejection"
    assert _kinds(app_id) == ["test_invite", "interview_invite", expected_last]

    # HR sees everything, candidates cannot reach HR endpoints
    assert client.get("/api/hr/overview").status_code == 403
    hr = make_client(HR_EMAIL)
    detail = hr.get(f"/api/hr/applications/{app_id}").json()["application"]
    assert detail["test"]["integrity"]["tab_switches"] == 1
    assert len(detail["emails"]) == 3 and detail["interview"]["transcript"]
    assert hr.get(f"/api/hr/applications/{app_id}/resume").status_code == 200


def test_weak_resume_is_rejected_and_cannot_take_test(make_client):
    client = make_client("amit@example.com")
    app = apply(client, "weak_resume.txt", years=0).json()["application"]
    assert app["stage"]["key"] == pipeline.ATS_REJECTED
    assert _kinds(app["id"]) == ["ats_rejection"]
    assert client.post(f"/api/applications/{app['id']}/test/start").status_code == 409


def test_failing_the_test_sends_rejection(make_client):
    client = make_client("rahul2@example.com")
    app_id = apply(client, "strong_resume_backend_developer.txt").json()["application"]["id"]
    client.post(f"/api/applications/{app_id}/test/start")
    result = client.post(f"/api/applications/{app_id}/test/submit", json={"answers": {}}).json()["application"]
    assert result["stage"]["key"] == pipeline.TEST_REJECTED
    assert client.post(f"/api/applications/{app_id}/interview/start").status_code == 409
    # resubmitting does not change anything or send another email
    client.post(f"/api/applications/{app_id}/test/submit", json={"answers": {}})
    assert _kinds(app_id) == ["test_invite", "test_rejection"]


def test_expired_test_uses_autosaved_answers(make_client, monkeypatch):
    client = make_client("late@example.com")
    app_id = apply(client, "strong_resume_backend_developer.txt").json()["application"]["id"]
    client.post(f"/api/applications/{app_id}/test/start")
    stored = db.mock_test_for_application(app_id)
    key = {q["id"]: q["answer_index"] for q in stored["questions"]}
    client.post(f"/api/applications/{app_id}/test/autosave", json={"answers": key})
    with db.connection() as conn:  # pretend the test started two hours ago
        conn.execute("UPDATE mock_tests SET started_at = '2020-01-01T00:00:00+00:00' WHERE application_id = ?", (app_id,))
    app = client.get(f"/api/applications/{app_id}").json()["application"]
    assert app["stage"]["key"] == pipeline.INTERVIEW_PENDING and app["test"]["percent"] == 100


def test_other_users_cannot_see_an_application(make_client):
    owner = make_client("owner@example.com")
    app_id = apply(owner, "strong_resume_backend_developer.txt").json()["application"]["id"]
    intruder = make_client("intruder@example.com")
    assert intruder.get(f"/api/applications/{app_id}").status_code == 404
    assert intruder.post(f"/api/applications/{app_id}/test/start").status_code == 404
