"""Scoring engines ported from the Job-Hunting-Agent project.

- ``resume`` / ``ats*``          : resume parsing and the deterministic ATS score
- ``mock_test*``                 : role-based MCQ test builder and grader
- ``interview_*`` / ``coding_problems`` : interview question selection and evaluation
- ``llm_client`` / ``guardrails``: optional LLM layer with budgets and prompt-injection framing

Keep these files close to the originals so fixes can be copied across both projects.
``ops_db`` and ``metrics`` are thin adapters onto this project's database.
"""
