from __future__ import annotations

import json
import sys
from typing import Any

from invariant.application import OperationResult
from invariant.errors import InvariantError
from invariant.protocol import Outcome


def emit(command: str, result: OperationResult, format_name: str) -> int:
    envelope = result.envelope(command)
    if format_name == "json":
        print(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False))
    else:
        print(f"{result.outcome.value.upper().replace('_', ' ')}: {command}")
        if result.result:
            print(json.dumps(result.result, indent=2, ensure_ascii=False))
    return 0


def emit_error(command: str, error: InvariantError, format_name: str) -> int:
    outcome = Outcome.BLOCKED if error.exit_code == 1 else Outcome.FAILED
    envelope: dict[str, Any] = {
        "protocol": 2,
        "command": command,
        "status": "blocked" if error.exit_code == 1 else "error",
        "outcome": outcome.value,
        "result": error.data or {},
        "diagnostics": [{"code": error.code, "message": error.message}],
    }
    if format_name == "json":
        print(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False))
    else:
        print(error.message, file=sys.stderr)
        for line in error.lines:
            print(line)
    return error.exit_code
