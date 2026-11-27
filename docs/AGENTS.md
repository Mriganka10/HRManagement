# Working on this codebase (humans and coding agents)

## Ground rules

1. **Business rules live in `services/`.** Routes in `api/` only parse input, resolve the signed-in user and call one service. Never put SQL or rules in a route.
2. **Choose the right guard** for every new endpoint: `require_candidate`, `require_employee` (the `me` dependency in `api/employee.py`), `require_hr` or `require_hr_admin`. Put it in the router for that audience. For anything addressed by ID, check ownership in the service.
3. **Make state changes compare-and-set**, e.g. `db.update(table, id, fields, where="status = 'pending'")` or `db.transition_stage(...)`. Check the return value and answer 409 if nothing changed.
4. **Audit** anything an auditor would ask about: `db.audit(actor_user_id, action, entity, entity_id, detail)`.
5. **Notify, don't fail.** Use `notifications.send_template(...)` and `notifications.notify(account_id, ...)`. They never raise.
6. **Schema changes are additive.**
   - New tables go in `schema.statements()`.
   - New columns go in `schema.ADDITIVE_COLUMNS` as `(table, column, definition)`.
   - Never rename or drop. Write SQL that works on SQLite and PostgreSQL: `?` placeholders, no vendor functions in queries (do date maths in Python), and JSON stored as TEXT with the column name added to `db.JSON_COLUMNS`.
7. **Settings**: add new settings to `settings.Settings`, `load_settings()`, `.env.example` and `docs/CONFIGURATION.md` together. Read them with `get_settings()`.
8. **Engines** (`engines/`) are shared with Job-Hunting-Agent.
   - Change them only for real fixes, and mark the change with an `HR-project change:` comment so it can be copied back.
   - The `JOB_AGENT_` → `HRM_` environment prefix is the only systematic difference.
9. **Sensitive fields** (PAN, bank details) go through `people.view(..., reveal=...)`. Never put them in lists, logs, LLM prompts or notifications.
10. **LLM use is optional and budgeted.**
    - Always use `engines/llm_client.call_json` with a strict schema, wrap user text with `guardrails.data_block` (done inside `call_json`), and keep a rule-based fallback that produces the same output shape.
    - Anything that changes data must be confirmed by a human.

## Front end

* There is no build step. Each portal is one script: `static/js/careers.js`, `me.js` or `hr.js`, plus `common.js`.
* Use the helpers in `window.HRM`:
  - `api`, `act` (busy button + error toast), `table`, `formDialog`, `confirmDialog`, `openDrawer`, `bars`, `pill`
  - formatters: `money` (₹, Indian grouping), `date`, `time`
  - `router` (hash routes)
* Escape every value you put into HTML with `esc()`.
* Copy: sentence case, plain verbs, buttons that say what happens ("Approve", "Generate payslips"), and errors that say how to fix the problem.
* Styles: one stylesheet, `static/css/app.css`. Colour encodes state only: teal = act, mint = done, amber = waiting, coral = stopped.

## Tests

* `pytest -q` must pass on SQLite, and on PostgreSQL with `HRM_TEST_DATABASE_URL`, before every push. CI runs both.
* Add a test for every new rule (eligibility, permissions, state transitions).
* Fixtures:
  - `hr_client`: a signed-in HR admin
  - `candidate_client(email)`: a signed-in candidate
  - `staff_client(app, user_id, password, change_to=...)`: a signed-in employee
* For a deterministic interview pass or fail, monkeypatch `services.interview.evaluate_interview`, as `tests/test_hiring_flow.py` does.

## Checklist for a new feature

- [ ] Service function(s) with validation and `ServiceError` messages a user can act on
- [ ] Route with the correct guard, in the correct router
- [ ] Audit and notifications
- [ ] UI section in the right portal, using the shared helpers
- [ ] Tests, including a permission test
- [ ] Docs: the feature doc and `API.md`
