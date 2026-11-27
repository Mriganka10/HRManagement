"""Business services. Routes call these; these call the engines, the database and the pipeline rules."""
from __future__ import annotations

from dataclasses import dataclass


class ServiceError(Exception):
    """A user-facing error with an HTTP status (translated to JSON by the web layer)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Notice:
    """An email the route should send in the background after responding."""

    kind: str
    application_id: int
    score: float
    threshold: float
    next_threshold: float | None = None
