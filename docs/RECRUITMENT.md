# Recruitment (AI-powered)

The agent runs the whole funnel without manual steps. HR sets up openings, watches the board, and steps in only where they choose to (`HRM_AUTO_SELECT=false`).

## 1. Job openings

HR creates openings under **HR → Job openings**. Each has a title, department, location, minimum experience, offer CTC, number of openings and **required skills**.

The job description is stored in a shape the ATS requirement parser reads cleanly:

```
<summary>
Responsibilities: ...
Required skills: Python, FastAPI, PostgreSQL, ...
Experience: 2+ years in a similar role.
```

* Keep the required skills to real must-haves; they drive the resume score.
* Avoid either/or pairs like "FastAPI or Django". The scorer treats them as two separate requirements.
* Closing an opening hides it from the careers page. Existing applications continue.
* On the very first start, openings are seeded from `catalog/roles.json`.

## 2. Resume screen: AI resume intelligence and the compatibility engine

`services/screening.py`, using `engines/ats.py`.

* **Upload checks**: PDF, DOCX, TXT or MD up to `HRM_MAX_UPLOAD_MB`. The file's bytes are checked (`%PDF`, `PK`), not just its extension. One application per role per email.
* **Extraction**: the resume parser recovers sections (contact, summary, experience, projects, education, skills, certifications), canonical skills and likely roles. This also feeds the onboarding prefill.
* **Score (0–100)**, compared against the opening:

| Category | Max points | What it measures |
|---|---|---|
| Structure | 18 | Contact details, standard sections, parseability |
| Skills & keywords | 32 | Coverage of the role's required skills and job-description keywords |
| Experience & projects | 35 | Evidence of relevant work, quantified impact, seniority versus minimum years |
| Writing quality | 15 | Action verbs, clarity, length |

* `ats_score >= HRM_ATS_PASS_SCORE` (75): the candidate moves to `test_pending` and gets the **mock test invite** email.
* Below the mark: `ats_rejected` and a polite **rejection** email.
* The candidate sees the breakdown, the skills found, the skills missing and how to improve.

Why the score is stricter than in Job-Hunting-Agent: there, the candidate compares the resume with their *own* skills. Here it is compared with the *employer's* requirements, which is the right test for shortlisting.

## 3. AI written assessment (mock test)

`services/assessment.py`, using `engines/mock_test.py`.

* **Questions**: role-specific MCQs chosen by topic relevance from the role's skills and description (Python, SQL, React, DSA, cloud, testing, BI and more), plus aptitude, reasoning and verbal questions.
  - Non-technical roles get aptitude, reasoning and verbal questions when the matched topics run out, not coding questions.
  - With an LLM key, missing skills get freshly generated questions.
* **Timer**:
  - Kept on the server from `started_at`. Answers are autosaved.
  - After the deadline plus grace, only the autosaved answers count.
  - The test is closed automatically the next time the candidate opens the portal.
* **Integrity**:
  - The answer key never reaches the browser, and correct answers are never revealed.
  - Tab switches and copy attempts are counted.
* **Pass**: at least 70% means `interview_pending` and the interview invite email. Below that, `test_rejected` and a rejection email.

## 4. AI interviewer

`services/interview.py`, using `engines/interview_*`.

* **Questions** come from the role, its skills and the candidate's level (from years of experience). The mix covers behavioural, technical, problem-solving and situational questions. Technical roles add **coding problems** with an editor.
* **Answering**:
  - The interviewer reads each question aloud (browser speech synthesis).
  - The candidate types or **speaks** the answer (speech recognition in Chrome or Edge).
  - Answers are autosaved after every question.
* **Scoring**: the evidence-based evaluator produces a rubric (communication, technical accuracy, confidence, problem solving) and an overall score. With an LLM key, an AI review is blended in.
  - Repeated, vague or off-topic answers score low.
  - Code is reviewed statically and never executed. Results reported by the browser are ignored.
* **Pass**: at least 75 leads to:
  - `selected` plus the **selection and onboarding** email when `HRM_AUTO_SELECT=true`;
  - otherwise `interview_passed` plus a **thank-you, next steps soon** email, and HR decides.
* **Fail**: `interview_rejected` and a rejection email.

## 5. Competency scorecard, SWOT and benchmarking

`services/evaluation.py`. Everything is derived from the evidence already measured, with no extra LLM call, so every number can be traced to its source.

| Competency | Evidence |
|---|---|
| Domain knowledge | Role-topic mock-test score + interview technical accuracy |
| Technical understanding | Resume skill match + interview technical accuracy + role-topic test score |
| Problem solving | Interview problem solving + aptitude and reasoning score |
| Communication | Interview communication + resume writing quality |
| Experience relevance | Resume experience and projects category |

* **SWOT**: competencies scoring 75 or more are strengths and those under 55 are development areas. Topic results add detail. Missing skills become opportunities (training). Below-minimum experience and integrity signals become concerns.
* **Benchmarking** (**HR → Benchmarking**): every candidate for a role who reached the test, ranked by overall score. Each competency is coloured against the role average.

## 6. Interview integrity monitoring

These are flags for human review and never automatic rejections:
* 3 or more tab switches in the test or interview
* copy attempts in the test
* 2 or more pasted interview answers
* a test closed by the timer
* a very fast high score: under 8 seconds per question with 80% or more

## 7. Recruitment intelligence (feedback loop)

`services/performance.py`. After people join, managers and HR record check-ins at 3, 6 and 12 months. **HR → Performance** correlates each recruitment signal (ATS, test, interview, each competency) with the average on-the-job rating for hires made through the portal. Over time this shows which assessment parameters actually predict success **at Kairoz**, so pass marks and question mixes can be tuned. At least 3 reviewed hires are needed per signal, and results become meaningful from about 20.

## Emails sent by the agent

| Outcome | Email kind |
|---|---|
| ATS pass / fail | `test_invite` / `ats_rejection` |
| Test pass / fail | `interview_invite` / `test_rejection` |
| Interview pass (auto) / pass (manual) / fail | `selected` / `interview_thanks` / `interview_rejection` |
| HR decision | `selected` / `not_selected` |
| Onboarding submitted | `welcome_credentials` |

Every email is logged in **HR → Email log** and on the candidate's timeline.
