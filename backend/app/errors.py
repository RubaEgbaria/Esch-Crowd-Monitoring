"""A single error type whose message is safe to show in the UI."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An expected failure with a clear, user-facing message.

    The API turns it into ``{"error": {"code", "message", "details"}}``
    with the given HTTP status.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
