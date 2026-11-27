"""Minimal metrics adapter for the ported engines (logs events, no analytics store yet)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("hr_management.metrics")


def emit(event: str, *, user_email: str = "", value: float | None = None, persist: bool = True, **props: Any) -> None:
    logger.debug("metric %s value=%s props=%s", event, value, props)


def item_analysis(days: int = 30, *, min_attempts: int = 8, include_all: bool = False) -> dict[str, Any]:
    # Empirical question difficulty needs real attempt data; until an analytics
    # store exists, every question keeps its curated difficulty label.
    return {"items": []}
