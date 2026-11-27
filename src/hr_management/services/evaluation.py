"""Candidate evaluation for HR: competency scorecard, evidence-based SWOT, benchmarking
against other candidates for the same role, and integrity flags.

Everything here is derived deterministically from what the pipeline already measured
(ATS report, mock-test topic scores, interview rubric, integrity counters), so every
statement can be traced to evidence. Nothing here makes the hiring decision; it informs HR.
"""
from __future__ import annotations

from statistics import mean

from .. import db

GENERAL_TOPICS = {"aptitude", "reasoning", "verbal"}
COMPETENCIES = ("Domain knowledge", "Technical understanding", "Problem solving", "Communication", "Experience relevance")


def _ats_category(report: dict | None, name: str) -> float | None:
    for row in (report or {}).get("score_breakdown") or []:
        if row.get("name") == name and row.get("max"):
            return round(100 * row["points"] / row["max"], 1)
    return None


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(mean(present), 1) if present else None


def scorecard(app: dict) -> dict:
    test = db.mock_test_for_application(app["id"]) or {}
    interview = db.interview_for_application(app["id"]) or {}
    card = test.get("scorecard") or {}
    topics = card.get("topic_breakdown") or []
    role_topics = [t for t in topics if t.get("topic") not in GENERAL_TOPICS and t.get("total")]
    general_topics = [t for t in topics if t.get("topic") in GENERAL_TOPICS and t.get("total")]
    role_pct = round(100 * sum(t["correct"] for t in role_topics) / sum(t["total"] for t in role_topics), 1) if role_topics else None
    general_pct = round(100 * sum(t["correct"] for t in general_topics) / sum(t["total"] for t in general_topics), 1) if general_topics else None
    rubric = (interview.get("report") or {}).get("rubric") or {}
    ats = app.get("ats_report") or {}
    values = {
        "Domain knowledge": _avg([role_pct, rubric.get("Technical accuracy")]),
        "Technical understanding": _avg([_ats_category(ats, "Skills & Keywords"), rubric.get("Technical accuracy"), role_pct]),
        "Problem solving": _avg([rubric.get("Problem solving"), general_pct]),
        "Communication": _avg([rubric.get("Communication"), _ats_category(ats, "Writing Quality")]),
        "Experience relevance": _ats_category(ats, "Experience & Projects"),
    }
    evidence = {
        "Domain knowledge": f"Role-topic test score {role_pct if role_pct is not None else '–'}%, interview technical accuracy {rubric.get('Technical accuracy', '–')}",
        "Technical understanding": f"Resume skills match {_ats_category(ats, 'Skills & Keywords') or '–'}%, interview technical accuracy {rubric.get('Technical accuracy', '–')}",
        "Problem solving": f"Interview problem solving {rubric.get('Problem solving', '–')}, aptitude & reasoning {general_pct if general_pct is not None else '–'}%",
        "Communication": f"Interview communication {rubric.get('Communication', '–')}, resume writing quality {_ats_category(ats, 'Writing Quality') or '–'}%",
        "Experience relevance": f"Resume experience & projects {_ats_category(ats, 'Experience & Projects') or '–'}%",
    }
    overall = _avg([app.get("ats_score"), app.get("test_percent"), app.get("interview_score")])
    return {"competencies": [{"name": k, "score": values[k], "evidence": evidence[k]} for k in COMPETENCIES],
            "overall": overall, "integrity": integrity_flags(test, interview)}


def integrity_flags(test: dict, interview: dict) -> list[dict]:
    flags = []
    ti = test.get("integrity") or {}
    ii = interview.get("integrity") or {}
    if int(ti.get("tab_switches", 0)) >= 3:
        flags.append({"level": "review", "text": f"Left the mock test tab {ti['tab_switches']} times."})
    if int(ti.get("copy_attempts", 0)) >= 1:
        flags.append({"level": "review", "text": f"Tried to copy test content {ti['copy_attempts']} time(s)."})
    if ti.get("late_submission"):
        flags.append({"level": "info", "text": "Mock test was closed by the timer (autosaved answers graded)."})
    if int(ii.get("tab_switches", 0)) >= 3:
        flags.append({"level": "review", "text": f"Left the interview tab {ii['tab_switches']} times."})
    if int(ii.get("paste_events", 0)) >= 2:
        flags.append({"level": "review", "text": f"Pasted text into {ii['paste_events']} interview answers."})
    started, completed = test.get("started_at"), test.get("completed_at")
    card = test.get("scorecard") or {}
    if started and completed and card.get("total"):
        seconds = (db.parse_time(completed) - db.parse_time(started)).total_seconds()  # type: ignore[operator]
        if seconds / max(1, card["total"]) < 8 and float(test.get("percent") or 0) >= 80:
            flags.append({"level": "review", "text": f"Very fast high score: {seconds:.0f}s for {card['total']} questions."})
    return flags


def swot(app: dict, card: dict | None = None) -> dict:
    card = card or scorecard(app)
    ats = app.get("ats_report") or {}
    interview = db.interview_for_application(app["id"]) or {}
    report = interview.get("report") or {}
    test = (db.mock_test_for_application(app["id"]) or {}).get("scorecard") or {}
    strengths, weaknesses, opportunities, threats = [], [], [], []
    for comp in card["competencies"]:
        if comp["score"] is None:
            continue
        if comp["score"] >= 75:
            strengths.append(f"{comp['name']} ({comp['score']:.0f}) — {comp['evidence']}.")
        elif comp["score"] < 55:
            weaknesses.append(f"{comp['name']} ({comp['score']:.0f}) — {comp['evidence']}.")
    for topic in test.get("topic_breakdown") or []:
        if topic.get("total", 0) >= 2 and topic.get("percent", 0) >= 80:
            strengths.append(f"Strong mock-test result in {topic['label']} ({topic['correct']}/{topic['total']}).")
        elif topic.get("total", 0) >= 2 and topic.get("percent", 100) < 50:
            weaknesses.append(f"Weak mock-test result in {topic['label']} ({topic['correct']}/{topic['total']}).")
    if ats.get("matched_keywords"):
        strengths.append("Resume shows required skills: " + ", ".join(ats["matched_keywords"][:6]) + ".")
    missing = list(ats.get("missing_keywords") or [])
    if missing:
        opportunities.append("Can be trained on missing role skills: " + ", ".join(missing[:5]) + ".")
    for item in (report.get("improvements") or [])[:2]:
        opportunities.append(f"Interview coaching point: {item}")
    if app.get("experience_years") is not None:
        role = db.fetch_one("SELECT min_years FROM job_openings WHERE key = ?", (app["role_key"],))
        if role and float(app["experience_years"]) < float(role["min_years"]):
            threats.append(f"Below the role's minimum experience ({app['experience_years']:g} vs {role['min_years']:g} years).")
    for flag in card["integrity"]:
        if flag["level"] == "review":
            threats.append(f"Integrity signal to review: {flag['text']}")
    return {"strengths": strengths[:6], "weaknesses": weaknesses[:6], "opportunities": opportunities[:5], "threats": threats[:5]}


def benchmark(role_key: str) -> dict:
    """Rank every candidate for a role who reached at least the mock test."""
    apps = db.fetch_all(
        "SELECT * FROM applications WHERE role_key = ? AND test_percent IS NOT NULL ORDER BY updated_at DESC", (role_key,))
    rows = []
    for app in apps:
        card = scorecard(app)
        rows.append({"id": app["id"], "name": app["full_name"], "stage": app["stage"], "ats": app.get("ats_score"),
                     "test": app.get("test_percent"), "interview": app.get("interview_score"), "overall": card["overall"],
                     "competencies": {c["name"]: c["score"] for c in card["competencies"]},
                     "flags": len([f for f in card["integrity"] if f["level"] == "review"])})
    rows.sort(key=lambda r: (r["overall"] or 0), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    averages = {name: _avg([r["competencies"].get(name) for r in rows]) for name in COMPETENCIES}
    return {"role_key": role_key, "candidates": rows, "averages": averages}
