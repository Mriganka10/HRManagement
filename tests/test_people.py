"""HRMS: accounts & sign-in, employees, leave routing, attendance, payroll, service desk, assistant."""
from datetime import date, timedelta

from conftest import staff_client
from hr_management import db
from hr_management.services import accounts, payroll


def _employee(hr_client, name, email, **extra):
    data = {"full_name": name, "email": email, "designation": "Engineer", "department": "Engineering",
            "date_of_joining": (date.today() - timedelta(days=400)).isoformat(), "annual_ctc": 1200000, "skills": "Python, AWS", **extra}
    r = hr_client.post("/api/hr/employees", json=data)
    assert r.status_code == 200, r.text
    return r.json()["employee"]


def _login_new(app, employee):
    password = accounts.reset_password(employee["account_id"], actor={"user_id": "test", "role": "hr_admin"})
    return staff_client(app, employee["employee_code"], password, change_to="Str0ngPassword1")


def _next_weekday(days: int) -> date:
    day = date.today() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def test_login_lockout_and_unique_ids(app, hr_client):
    a = _employee(hr_client, "Asha Rao", "asha@kairoz.test")
    b = _employee(hr_client, "Bala K", "bala@kairoz.test")
    assert a["employee_code"] != b["employee_code"] and a["employee_code"].startswith("KZE")
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"user_id": a["employee_code"], "password": "wrong-password"}).status_code == 401
    locked = client.post("/api/auth/login", json={"user_id": a["employee_code"], "password": "wrong-password"})
    assert locked.status_code == 423
    assert hr_client.post("/api/hr/employees", json={"full_name": "Dup", "email": "asha@kairoz.test"}).status_code == 409


def test_password_rules_and_session_invalidation(app, hr_client):
    emp = _employee(hr_client, "Chitra M", "chitra@kairoz.test")
    password = accounts.reset_password(emp["account_id"], actor={"user_id": "t", "role": "hr_admin"})
    client = staff_client(app, emp["employee_code"], password)
    weak = client.post("/api/auth/change-password", json={"current_password": password, "new_password": "short"})
    assert weak.status_code == 400
    old_cookie_client = staff_client(app, emp["employee_code"], password)
    assert client.post("/api/auth/change-password", json={"current_password": password, "new_password": "GoodPassw0rd!"}).status_code == 200
    assert client.get("/api/me/home").status_code == 200
    assert old_cookie_client.get("/api/auth/me").status_code == 401  # other sessions signed out


def test_leave_routes_to_manager_and_updates_balance(app, hr_client):
    manager = _employee(hr_client, "Mona Manager", "mona@kairoz.test")
    report = _employee(hr_client, "Ravi Report", "ravi@kairoz.test", manager_id=manager["id"])
    emp = _login_new(app, report)
    mgr = _login_new(app, manager)
    start = _next_weekday(3).isoformat()
    check = emp.post("/api/me/leave/check", json={"leave_type": "CL", "start_date": start, "end_date": start}).json()
    assert check["eligible"] and check["days"] == 1
    too_long = emp.post("/api/me/leave/check", json={"leave_type": "CL", "start_date": start,
                                                     "end_date": (date.fromisoformat(start) + timedelta(days=10)).isoformat()}).json()
    assert not too_long["eligible"]
    request = emp.post("/api/me/leave", json={"leave_type": "CL", "start_date": start, "end_date": start, "reason": "Family"}).json()["request"]
    assert request["approver_name"] == "Mona Manager"
    assert emp.post("/api/me/leave", json={"leave_type": "CL", "start_date": start, "end_date": start}).status_code == 400  # overlap
    team = mgr.get("/api/me/team").json()
    assert team["pending"][0]["id"] == request["id"]
    assert mgr.post(f"/api/me/team/leave/{request['id']}/decision", json={"approve": True}).status_code == 200
    balance = next(b for b in emp.get("/api/me/leave").json()["balances"] if b["code"] == "CL")
    assert balance["used"] == 1
    assert db.fetch_one("SELECT status FROM attendance WHERE work_date = ?", (start,))["status"] == "on_leave"


def test_payroll_lop_and_explanation(app, hr_client):
    emp = _employee(hr_client, "Payal P", "payal@kairoz.test", annual_ctc=600000)
    last = date.today().replace(day=1) - timedelta(days=1)
    period = f"{last.year}-{last.month:02d}"
    lwp = db.fetch_one("SELECT id FROM leave_types WHERE code = 'LWP'")
    day = last.replace(day=10)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    db.insert("leave_requests", {"employee_id": emp["id"], "leave_type_id": lwp["id"], "start_date": day.isoformat(), "end_date": day.isoformat(),
                                 "days": 1, "half_day": 0, "reason": "", "status": "approved", "created_at": db.now_iso()})
    r = hr_client.post("/api/hr/payroll/run", json={"period": period}).json()
    assert r["generated"] >= 1
    slip = db.fetch_one("SELECT * FROM payslips WHERE employee_id = ? AND period = ?", (emp["id"], period))
    assert slip["lop_days"] == 1 and slip["paid_days"] == slip["working_days"] - 1
    full = payroll.default_components(600000)
    assert slip["gross"] < full["basic"] + full["hra"] + full["special_allowance"]
    assert "Provident Fund (employee)" in slip["deductions"]
    assert any("loss of pay" in line for line in payroll.explain(slip))
    emp_client = _login_new(app, emp)
    assert emp_client.get(f"/api/me/payslips/{slip['id']}/view").status_code == 200


def test_service_desk_attendance_correction_and_document(app, hr_client):
    emp = _employee(hr_client, "Dev D", "dev@kairoz.test")
    client = _login_new(app, emp)
    yesterday = _next_weekday(-7).isoformat()
    req = client.post("/api/me/requests", data={"kind": "attendance_correction", "work_date": yesterday, "check_in_time": "09:40",
                                                "check_out_time": "18:30", "description": "Forgot"}).json()["request"]
    assert req["ref"].startswith("REQ-")
    hr_client.post(f"/api/hr/requests/{req['id']}/resolve", json={"status": "approved", "resolution": "Fixed"})
    record = db.fetch_one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?", (emp["id"], yesterday))
    assert record["source"] == "correction" and record["check_in"][11:16] == "09:40"
    doc_req = client.post("/api/me/requests", data={"kind": "document", "category": "Employment certificate"}).json()["request"]
    hr_client.post(f"/api/hr/requests/{doc_req['id']}/resolve", json={"status": "approved", "resolution": ""})
    docs = client.get("/api/me/documents").json()["documents"]
    assert docs and client.get(f"/api/me/documents/{docs[0]['id']}").status_code == 200
    other = _login_new(app, _employee(hr_client, "Other O", "other@kairoz.test"))
    assert other.get(f"/api/me/requests/{req['id']}").status_code == 404
    assert other.get(f"/api/me/documents/{docs[0]['id']}").status_code == 404


def test_assistant_plans_and_requires_confirmation(app, hr_client):
    emp = _employee(hr_client, "Isha I", "isha@kairoz.test")
    client = _login_new(app, emp)
    balance = client.post("/api/me/assistant", json={"message": "How many leaves do I have left?"}).json()
    assert balance["tool"] == "leave_balance" and balance["cards"]
    start = _next_weekday(5)
    ask = client.post("/api/me/assistant", json={"message": f"I need casual leave on {start.day} {start.strftime('%b')}"}).json()
    assert ask["action"]["tool"] == "apply_leave"
    assert not db.fetch_all("SELECT id FROM leave_requests WHERE employee_id = ?", (emp["id"],))  # nothing until confirmed
    done = client.post("/api/me/assistant/confirm", json={"action": ask["action"]}).json()
    assert "Done" in done["reply"] and db.fetch_all("SELECT id FROM leave_requests WHERE employee_id = ?", (emp["id"],))
    policy = client.post("/api/me/assistant", json={"message": "What is the notice period?"}).json()
    assert policy["tool"] == "policy" and "60-day" in policy["reply"]
    unknown = client.post("/api/me/assistant", json={"message": "What is the maternity leave policy?"}).json()
    assert unknown["action"]["tool"] == "raise_ticket"  # does not guess
    assert client.post("/api/me/assistant/confirm", json={"action": {"tool": "delete_everything"}}).status_code == 400


def test_role_boundaries(app, hr_client):
    emp = _employee(hr_client, "Esha E", "esha@kairoz.test")
    client = _login_new(app, emp)
    for path in ("/api/hr/dashboard", "/api/hr/employees", "/api/hr/payroll", f"/api/hr/employees/{emp['id']}"):
        assert client.get(path).status_code == 403
    assert client.post(f"/api/hr/accounts/{emp['account_id']}/reset-password").status_code == 403
    assert hr_client.get("/api/hr/talent/skills").status_code == 200
    page = client.get("/hr", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/me"


def test_talent_search_and_intelligence(app, hr_client):
    _employee(hr_client, "Tara T", "tara@kairoz.test", skills="Python, AWS, Docker, Kubernetes")
    _employee(hr_client, "Uma U", "uma@kairoz.test", skills="Python")
    r = hr_client.post("/api/hr/talent/search", json={"required": "Python, AWS"}).json()
    assert [x["name"] for x in r["ready"]] == ["Tara T"] and r["trainable"][0]["name"] == "Uma U"
    assert r["trainable"][0]["training"][0]["skill"] == "AWS"
    intel = hr_client.get("/api/hr/performance/intelligence").json()
    assert "signals" in intel


def test_cross_site_post_blocked(app, hr_client):
    r = hr_client.post("/api/hr/policies", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_new_employee_can_sign_in_on_a_browser_where_hr_is_signed_in(app, hr_client):
    """Regression: HR adds an employee, then the employee signs in on the same browser.

    /login and / used to redirect any signed-in user to their own portal, so with HR still signed
    in the employee sign-in form never appeared. The emailed password must also work when it is
    copied with surrounding whitespace.
    """
    import re
    from hr_management.settings import get_settings

    employee = _employee(hr_client, "Neha Ghosh", "neha.ghosh@example.com")
    outbox = sorted((get_settings().outbox_dir).glob("*welcome_credentials*"))
    html = outbox[-1].read_text(encoding="utf-8")
    user_id = re.search(r"User ID</td><td[^>]*>([^<]+)<", html).group(1)
    password = re.search(r"Temporary password</td><td[^>]*>([^<]+)<", html).group(1)
    assert user_id == employee["employee_code"]
    assert "/login?as=employee" in html

    browser = hr_client  # same cookie jar: HR is signed in
    for path in ("/", "/login", "/login?as=employee"):
        page = browser.get(path, follow_redirects=False)
        assert page.status_code == 200, path
    assert 'id="login-form"' in browser.get("/login?as=employee").text

    r = browser.post("/api/auth/login", json={"user_id": user_id.lower(), "password": f" {password}\n"})
    assert r.status_code == 200, r.text
    assert r.json()["redirect"] == "/password"
    assert browser.get("/api/auth/me").json()["user_id"] == user_id  # the HR session was replaced
    r = browser.post("/api/auth/change-password", json={"current_password": password, "new_password": "Sunrise2026x"})
    assert r.status_code == 200 and r.json()["redirect"] == "/me"
    assert browser.get("/me", follow_redirects=False).status_code == 200
    assert browser.get("/api/me/home").status_code == 200


def test_short_email_name_does_not_block_passwords(app, hr_client):
    # hr@… must be able to pick a password containing the letters "hr".
    from conftest import HR_PASSWORD

    r = hr_client.post("/api/auth/change-password", json={"current_password": HR_PASSWORD, "new_password": "Threshold2026"})
    assert r.status_code == 200, r.text
