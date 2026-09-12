from __future__ import annotations

import json
import sys
from typing import Any

from invariant.application import OperationResult
from invariant.errors import InvariantError
from invariant.protocol import Outcome, PROTOCOL_VERSION


def _line_value(lines: object, key: str, fallback: str = "—") -> str:
    if not isinstance(lines, list):
        return fallback
    prefix = key + ": "
    return next(
        (line[len(prefix) :] for line in lines if isinstance(line, str) and line.startswith(prefix)),
        fallback,
    )


def _emit_initialize(result: OperationResult) -> None:
    policy = result.result.get("policy", [])
    commit = str(result.result.get("commit") or "—")
    print("INVARIANT  repository initialized")
    print("│")
    print(f"├─ intent       {_line_value(policy, 'authority.intent.suppliers')}")
    print(f"├─ resolution   {_line_value(policy, 'authority.resolution.delegation')}")
    print(
        "├─ execution    parallel work · "
        f"{_line_value(policy, 'execution.transitions')} transitions"
    )
    print("├─ lifecycle    Git-grounded")
    print(f"└─ policy       .invariant/config.yml @ {commit[:12]}")


def _emit_state(result: OperationResult) -> None:
    values = result.result
    governance = values.get("governance", {})
    policy = values.get("policy", {})
    authority = policy.get("authority", {}) if isinstance(policy, dict) else {}
    intent = authority.get("intent", {}) if isinstance(authority, dict) else {}
    resolution = authority.get("resolution", {}) if isinstance(authority, dict) else {}
    changes = values.get("changes", [])
    print("INVARIANT  repository valid")
    print("│")
    print(f"├─ intent       {', '.join(intent.get('suppliers', [])) or '—'}")
    print(f"├─ resolution   {resolution.get('delegation', '—')}")
    print(f"├─ kernel       {governance.get('records', 0)} accepted records")
    print(f"├─ lifecycle    {len(changes) if isinstance(changes, list) else 0} active changes")
    print(f"└─ target       {policy.get('integration_branch', '—') if isinstance(policy, dict) else '—'}")


def emit(command: str, result: OperationResult, format_name: str) -> int:
    envelope = result.envelope(command)
    if format_name == "json":
        print(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False))
    elif command == "init":
        _emit_initialize(result)
    elif command == "state.validate":
        _emit_state(result)
    else:
        print(f"{result.outcome.value.upper().replace('_', ' ')}: {command}")
        if result.result:
            print(json.dumps(result.result, indent=2, ensure_ascii=False))
    return 0


def emit_error(command: str, error: InvariantError, format_name: str) -> int:
    outcome = Outcome.BLOCKED if error.exit_code == 1 else Outcome.FAILED
    envelope: dict[str, Any] = {
        "protocol": PROTOCOL_VERSION,
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
