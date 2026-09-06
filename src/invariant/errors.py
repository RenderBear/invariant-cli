from __future__ import annotations

from typing import Any


class InvariantError(Exception):
    """A user-visible failure with a stable process and diagnostic class."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = 2,
        code: str = "operation_failed",
        lines: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.code = code
        self.lines = lines or []
        self.data = data


class Blocked(InvariantError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "operation_blocked",
        lines: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, exit_code=1, code=code, lines=lines, data=data)


class RemotePushFailed(Blocked):
    """A remote push failed after the verified local landing completed."""

    def __init__(self, message: str, *, lines: list[str]) -> None:
        super().__init__(message, code="remote_push_failed", lines=lines)


class UsageError(InvariantError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=2, code="invalid_invocation")
