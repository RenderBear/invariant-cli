from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any

from invariant.errors import InvariantError


@dataclass(frozen=True)
class CommandResult:
    lines: list[str]
    data: dict[str, Any] | list[Any]
    outcome: str = "completed"


def _records(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for line in lines:
        match = re.match(r"^([A-Z][A-Z0-9-]*): (.*)$", line)
        if match:
            result.append({"name": match.group(1), "value": match.group(2)})
    return result


def emit_success(
    command: str,
    result: list[str] | CommandResult,
    format_name: str,
    *,
    verbose: bool = False,
) -> int:
    lines = result.lines if isinstance(result, CommandResult) else result
    if format_name == "json":
        payload: dict[str, Any] | list[Any]
        payload = result.data if isinstance(result, CommandResult) else {"records": _records(lines)}
        if verbose and isinstance(payload, dict):
            payload = {**payload, "output": "\n".join(lines) + ("\n" if lines else "")}
        print(
            json.dumps(
                {
                    "protocol": 2,
                    "command": command,
                    "status": "ok",
                    "outcome": result.outcome if isinstance(result, CommandResult) else "completed",
                    "result": payload,
                    "diagnostics": [],
                },
                separators=(",", ":"),
            )
        )
    elif lines:
        print("\n".join(lines))
    return 0


def emit_error(
    command: str, error: InvariantError, format_name: str, *, verbose: bool = False
) -> int:
    lines = list(error.lines)
    if format_name == "json":
        status = "blocked" if error.exit_code == 1 else "error"
        result: dict[str, Any] = error.data or {"records": _records(lines)}
        if error.data is not None and lines:
            result = {**result, "records": _records(lines)}
        if verbose:
            result["output"] = "\n".join(lines) + ("\n" if lines else "")
        print(
            json.dumps(
                {
                    "protocol": 2,
                    "command": command,
                    "status": status,
                    "outcome": "blocked" if status == "blocked" else "failed",
                    "result": result,
                    "diagnostics": [{"code": error.code, "message": error.message}],
                },
                separators=(",", ":"),
            )
        )
    else:
        if lines:
            print("\n".join(lines))
        print(error.message, file=sys.stderr)
    return error.exit_code
