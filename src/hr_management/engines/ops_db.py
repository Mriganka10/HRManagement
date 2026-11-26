"""Adapter that gives the ported engines the storage hooks they expect.

The engines in this package were taken from the Job-Hunting-Agent project, where
``ops_db`` is a full operations database. Here it simply forwards the three calls
the engines make (rate limits and LLM spend tracking) to ``hr_management.db``,
so the engine files stay almost identical to the originals and are easy to sync.
"""
from __future__ import annotations


def rate_hit(bucket: str, limit: int, window_seconds: int, *, now: float | None = None) -> tuple[bool, int]:
    from .. import db

    return db.rate_hit(bucket, limit, window_seconds, now=now)


def llm_spend(day: str | None = None, *, user_email: str = "") -> float:
    from .. import db

    return db.llm_spend(user_email=user_email)


def record_llm_usage(feature: str, *, user_email: str = "", input_tokens: int, output_tokens: int, cost_usd: float, ok: bool) -> None:
    from .. import db

    db.record_llm_usage(feature, user_email=user_email, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd, ok=ok)
