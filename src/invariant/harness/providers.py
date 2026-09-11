from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class AgentProvider(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"


_PROVIDER_ENV = {
    AgentProvider.CODEX: "INVARIANT_CODEX",
    AgentProvider.CLAUDE: "INVARIANT_CLAUDE",
}

_BUNDLED_EXECUTABLES = {
    AgentProvider.CODEX: (
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    ),
    AgentProvider.CLAUDE: (),
}


class AgentInvocationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "agent_invocation_failed",
        exit_code: int = 2,
        lines: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.lines = lines or []
        self.data = data


@dataclass(frozen=True)
class AgentResult:
    provider: AgentProvider
    response: dict[str, Any]
    session_id: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class AgentWriteResult:
    provider: AgentProvider
    message: str
    session_id: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class ProviderStatus:
    provider: AgentProvider
    available: bool
    executable: str
    version: str
    hint: str


@dataclass(frozen=True)
class ConnectionStatus:
    provider: AgentProvider
    installed: bool
    authenticated: bool
    executable: str
    version: str
    detail: str
    hint: str


def executable(provider: AgentProvider) -> str | None:
    environment_name = _PROVIDER_ENV[provider]
    configured = os.environ.get(environment_name)
    if configured:
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None

    resolved = shutil.which(provider.value)
    if resolved:
        return resolved

    for candidate in _BUNDLED_EXECUTABLES[provider]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def discovery_hint(provider: AgentProvider) -> str:
    environment_name = _PROVIDER_ENV[provider]
    return (
        f"install and sign in to {provider.value}, then put it on PATH or set "
        f"{environment_name}=/path/to/{provider.value}"
    )


def status(provider: AgentProvider) -> ProviderStatus:
    path = executable(provider)
    if path is None:
        return ProviderStatus(provider, False, "", "", discovery_hint(provider))
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProviderStatus(provider, False, path, "", discovery_hint(provider))
    version = (completed.stdout or completed.stderr).strip().splitlines()
    return ProviderStatus(
        provider,
        completed.returncode == 0,
        path,
        version[0] if version else "",
        "" if completed.returncode == 0 else discovery_hint(provider),
    )


def _authentication_command(provider: AgentProvider, path: str) -> list[str]:
    if provider == AgentProvider.CODEX:
        return [path, "login", "status"]
    return [path, "auth", "status"]


def _login_command(provider: AgentProvider, path: str) -> list[str]:
    if provider == AgentProvider.CODEX:
        return [path, "login"]
    return [path, "auth", "login"]


def connection_status(provider: AgentProvider) -> ConnectionStatus:
    installed = status(provider)
    if not installed.available:
        return ConnectionStatus(
            provider,
            False,
            False,
            installed.executable,
            installed.version,
            "",
            installed.hint,
        )
    try:
        completed = subprocess.run(
            _authentication_command(provider, installed.executable),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ConnectionStatus(
            provider,
            True,
            False,
            installed.executable,
            installed.version,
            "could not verify the native CLI login",
            f"run 'invariant connect {provider.value}'",
        )
    detail = (completed.stdout or completed.stderr).strip()
    return ConnectionStatus(
        provider,
        True,
        completed.returncode == 0,
        installed.executable,
        installed.version,
        detail,
        "" if completed.returncode == 0 else f"run 'invariant connect {provider.value}'",
    )


def connect(provider: AgentProvider) -> ConnectionStatus:
    installed = status(provider)
    if not installed.available:
        raise AgentInvocationError(
            f"{provider.value} is not installed; {discovery_hint(provider)}",
            code="missing_agent",
        )
    current = connection_status(provider)
    if current.authenticated:
        return current
    try:
        completed = subprocess.run(
            _login_command(provider, installed.executable),
            check=False,
        )
    except OSError as exc:
        raise AgentInvocationError(
            f"could not start {provider.value} login: {exc}", code="agent_login_failed"
        ) from exc
    if completed.returncode:
        raise AgentInvocationError(
            f"{provider.value} login exited with status {completed.returncode}",
            code="agent_login_failed",
        )
    refreshed = connection_status(provider)
    if not refreshed.authenticated:
        raise AgentInvocationError(
            f"{provider.value} did not report an authenticated session after login",
            code="agent_login_failed",
        )
    return refreshed


def _failure(provider: AgentProvider, completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode == 0:
        return
    detail = (completed.stderr or completed.stdout).strip()
    if len(detail) > 4000:
        detail = detail[-4000:]
    suffix = f": {detail}" if detail else ""
    raise AgentInvocationError(
        f"{provider.value} exited with status {completed.returncode}{suffix}"
    )


def _object(value: object, provider: AgentProvider) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentInvocationError(
            f"{provider.value} returned structured output that is not a JSON object",
            code="invalid_agent_output",
        )
    return value


def _json_schema_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _nullable_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if "const" in schema or "default" in schema:
        return schema
    result = dict(schema)
    raw_type = result.get("type")
    if isinstance(raw_type, str):
        result["type"] = [raw_type, "null"]
    elif isinstance(raw_type, list):
        result["type"] = list(dict.fromkeys([*raw_type, "null"]))
    elif isinstance(result.get("anyOf"), list):
        result["anyOf"] = [*result["anyOf"], {"type": "null"}]
    else:
        raise AgentInvocationError(
            "codex output schema has an optional field that cannot be made nullable",
            code="unsupported_output_schema",
        )
    enum = result.get("enum")
    if isinstance(enum, list) and None not in enum:
        result["enum"] = [*enum, None]
    return result


def _codex_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate a JSON schema into Codex's strict Structured Outputs subset."""

    def normalize(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
        result = copy.deepcopy(value)
        properties = result.get("properties")
        original_required = set(result.get("required", []))
        if isinstance(properties, dict):
            normalized_properties: dict[str, Any] = {}
            for name, child in properties.items():
                if not isinstance(child, dict):
                    raise AgentInvocationError(
                        f"codex output schema property {'.'.join((*path, name))} is invalid",
                        code="unsupported_output_schema",
                    )
                normalized = normalize(child, (*path, name))
                normalized_properties[name] = (
                    normalized
                    if name in original_required
                    else _nullable_schema(normalized)
                )
            result["properties"] = normalized_properties

        for keyword in ("$defs", "definitions"):
            definitions = result.get(keyword)
            if isinstance(definitions, dict):
                result[keyword] = {
                    name: normalize(child, (*path, keyword, name))
                    for name, child in definitions.items()
                    if isinstance(child, dict)
                }
        items = result.get("items")
        if isinstance(items, dict):
            result["items"] = normalize(items, (*path, "items"))
        for keyword in ("anyOf",):
            alternatives = result.get(keyword)
            if isinstance(alternatives, list):
                result[keyword] = [
                    normalize(child, (*path, keyword, str(index)))
                    for index, child in enumerate(alternatives)
                    if isinstance(child, dict)
                ]
        unsupported = next(
            (
                keyword
                for keyword in ("allOf", "oneOf", "not", "if", "then", "else")
                if keyword in result
            ),
            None,
        )
        if unsupported:
            location = ".".join(path) or "<root>"
            raise AgentInvocationError(
                f"codex output schema at {location} uses unsupported '{unsupported}'",
                code="unsupported_output_schema",
            )

        if "type" not in result:
            literals: list[object] = []
            if "const" in result:
                literals = [result["const"]]
            elif isinstance(result.get("enum"), list) and result["enum"]:
                literals = result["enum"]
            if literals:
                types = list(dict.fromkeys(_json_schema_type(item) for item in literals))
                result["type"] = types[0] if len(types) == 1 else types

        raw_type = result.get("type")
        types = {raw_type} if isinstance(raw_type, str) else set(raw_type or [])
        if "object" in types:
            if "additionalProperties" not in result and isinstance(
                result.get("properties"), dict
            ):
                result["additionalProperties"] = False
            if result.get("additionalProperties") is not False:
                location = ".".join(path) or "<root>"
                raise AgentInvocationError(
                    f"codex output schema contains an open object at {location}",
                    code="unsupported_output_schema",
                )
            if isinstance(result.get("properties"), dict):
                result["required"] = list(result["properties"])

        result.pop("default", None)
        result.pop("uniqueItems", None)
        return result

    return normalize(schema, ())


def _restore_codex_response(value: Any, schema: dict[str, Any]) -> Any:
    if isinstance(value, list):
        items = schema.get("items")
        return (
            [_restore_codex_response(item, items) for item in value]
            if isinstance(items, dict)
            else value
        )
    if not isinstance(value, dict):
        return value
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return value
    required = set(schema.get("required", []))
    restored: dict[str, Any] = {}
    for name, item in value.items():
        child = properties.get(name)
        if item is None and name not in required:
            continue
        restored[name] = (
            _restore_codex_response(item, child)
            if isinstance(child, dict)
            else item
        )
    return restored


def _invoke_codex(
    path: str,
    cwd: Path,
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str | None,
    timeout: int,
    persistent: bool = False,
    session_id: str | None = None,
) -> AgentResult:
    with tempfile.TemporaryDirectory(prefix="invariant-agent-codex.") as directory:
        root = Path(directory)
        schema_path = root / "schema.json"
        output_path = root / "response.json"
        schema_path.write_text(
            json.dumps(_codex_output_schema(schema), separators=(",", ":")),
            encoding="utf-8",
        )
        options = [
            "--ignore-user-config",
            "--ignore-rules",
            "--config",
            "mcp_servers={}",
            "--config",
            "hooks={}",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if session_id is None:
            options[0:0] = ["--sandbox", "read-only", "--color", "never"]
            if not persistent:
                options.insert(0, "--ephemeral")
        else:
            # A resumed turn must restate the boundary; it cannot inherit it from the first turn.
            options.extend(["--config", 'sandbox_mode="read-only"'])
        if model:
            options.extend(["--model", model])
        argv = (
            [path, "exec", "resume", *options, session_id, "-"]
            if session_id is not None
            else [path, "exec", *options, "-"]
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                input=prompt,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentInvocationError(
                f"codex did not finish within {timeout} seconds", code="agent_timeout"
            ) from exc
        except OSError as exc:
            raise AgentInvocationError(f"could not start codex: {exc}") from exc
        _failure(AgentProvider.CODEX, completed)
        if not output_path.is_file():
            raise AgentInvocationError(
                "codex completed without writing its structured response",
                code="invalid_agent_output",
            )
        try:
            response = _object(
                _restore_codex_response(
                    json.loads(output_path.read_text(encoding="utf-8")), schema
                ),
                AgentProvider.CODEX,
            )
        except json.JSONDecodeError as exc:
            raise AgentInvocationError(
                f"codex returned invalid JSON: {exc}", code="invalid_agent_output"
            ) from exc

        returned_session_id = session_id or ""
        usage: dict[str, Any] = {}
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started":
                returned_session_id = str(event.get("thread_id") or returned_session_id)
            elif event.get("type") == "turn.completed" and isinstance(
                event.get("usage"), dict
            ):
                usage = dict(event["usage"])
        return AgentResult(AgentProvider.CODEX, response, returned_session_id, usage)


def _invoke_claude(
    path: str,
    cwd: Path,
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str | None,
    timeout: int,
    persistent: bool = False,
    session_id: str | None = None,
) -> AgentResult:
    instruction = (
        "Resolve the read-only Invariant request supplied on stdin. Inspect the current "
        "repository when needed and return only the requested structured result."
    )
    argv = [
        path,
        "-p",
        "--restricted",
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep",
        "--disallowedTools",
        "mcp__*",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, separators=(",", ":")),
    ]
    if not persistent:
        argv.append("--no-session-persistence")
    if session_id is not None:
        argv.extend(["--resume", session_id])
    if model:
        argv.extend(["--model", model])
    argv.append(instruction)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            input=prompt,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentInvocationError(
            f"claude did not finish within {timeout} seconds", code="agent_timeout"
        ) from exc
    except OSError as exc:
        raise AgentInvocationError(f"could not start claude: {exc}") from exc
    _failure(AgentProvider.CLAUDE, completed)
    try:
        envelope = _object(json.loads(completed.stdout), AgentProvider.CLAUDE)
    except json.JSONDecodeError as exc:
        raise AgentInvocationError(
            f"claude returned invalid JSON: {exc}", code="invalid_agent_output"
        ) from exc
    response = _object(envelope.get("structured_output"), AgentProvider.CLAUDE)
    usage = dict(envelope.get("usage")) if isinstance(envelope.get("usage"), dict) else {}
    if envelope.get("total_cost_usd") is not None:
        usage["estimated_cost_usd"] = envelope["total_cost_usd"]
    return AgentResult(
        AgentProvider.CLAUDE,
        response,
        str(envelope.get("session_id") or session_id or ""),
        usage,
    )


def invoke(
    provider: AgentProvider,
    cwd: Path,
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str | None = None,
    timeout: int = 600,
) -> AgentResult:
    path = executable(provider)
    if path is None:
        raise AgentInvocationError(
            f"{provider.value} is unavailable; {discovery_hint(provider)}",
            code="missing_agent",
        )
    if provider == AgentProvider.CODEX:
        return _invoke_codex(path, cwd, prompt, schema, model=model, timeout=timeout)
    return _invoke_claude(path, cwd, prompt, schema, model=model, timeout=timeout)


def invoke_session(
    provider: AgentProvider,
    cwd: Path,
    prompt: str,
    schema: dict[str, Any],
    *,
    session_id: str | None = None,
    model: str | None = None,
    timeout: int = 600,
) -> AgentResult:
    """Run one persistent, read-only turn for an Invariant console session."""

    path = executable(provider)
    if path is None:
        raise AgentInvocationError(
            f"{provider.value} is unavailable; {discovery_hint(provider)}",
            code="missing_agent",
        )
    result = (
        _invoke_codex(
            path,
            cwd,
            prompt,
            schema,
            model=model,
            timeout=timeout,
            persistent=True,
            session_id=session_id,
        )
        if provider == AgentProvider.CODEX
        else _invoke_claude(
            path,
            cwd,
            prompt,
            schema,
            model=model,
            timeout=timeout,
            persistent=True,
            session_id=session_id,
        )
    )
    if not result.session_id:
        raise AgentInvocationError(
            f"{provider.value} did not return a resumable session ID",
            code="missing_session_id",
        )
    return result


def _invoke_codex_write(
    path: str,
    cwd: Path,
    prompt: str,
    *,
    model: str | None,
    timeout: int,
) -> AgentWriteResult:
    with tempfile.TemporaryDirectory(prefix="invariant-agent-codex-write.") as directory:
        output_path = Path(directory) / "response.txt"
        argv = [
            path,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--config",
            "mcp_servers={}",
            "--config",
            "hooks={}",
            "--sandbox",
            "workspace-write",
            "--color",
            "never",
            "--json",
            "--output-last-message",
            str(output_path),
        ]
        if model:
            argv.extend(["--model", model])
        argv.append("-")
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                input=prompt,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentInvocationError(
                f"codex did not finish within {timeout} seconds", code="agent_timeout"
            ) from exc
        except OSError as exc:
            raise AgentInvocationError(f"could not start codex: {exc}") from exc
        _failure(AgentProvider.CODEX, completed)
        if not output_path.is_file():
            raise AgentInvocationError(
                "codex completed without writing its final response",
                code="invalid_agent_output",
            )
        session_id = ""
        usage: dict[str, Any] = {}
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started":
                session_id = str(event.get("thread_id") or "")
            elif event.get("type") == "turn.completed" and isinstance(
                event.get("usage"), dict
            ):
                usage = dict(event["usage"])
        return AgentWriteResult(
            AgentProvider.CODEX,
            output_path.read_text(encoding="utf-8").strip(),
            session_id,
            usage,
        )


def _invoke_claude_write(
    path: str,
    cwd: Path,
    prompt: str,
    *,
    model: str | None,
    timeout: int,
) -> AgentWriteResult:
    instruction = (
        "Implement the Invariant-managed repository change supplied on stdin. Work only in "
        "the current checkout and return a concise final summary."
    )
    # Claude Code offers no process sandbox here, so the effects Invariant owns — commits,
    # publication, ref movement, and its own runtime — are denied at the tool boundary.
    denied = ",".join(
        [
            "mcp__*",
            "Bash(git commit:*)",
            "Bash(git push:*)",
            "Bash(git update-ref:*)",
            "Bash(git worktree:*)",
            "Bash(git branch:*)",
            "Bash(git switch:*)",
            "Bash(git checkout:*)",
            "Bash(git reset:*)",
            "Bash(invariant:*)",
            "Bash(invariant-agent:*)",
        ]
    )
    argv = [
        path,
        "-p",
        "--bare",
        "--permission-mode",
        "acceptEdits",
        "--tools",
        "Read,Glob,Grep,Edit,Write,Bash",
        "--disallowedTools",
        denied,
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    if model:
        argv.extend(["--model", model])
    argv.append(instruction)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            input=prompt,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentInvocationError(
            f"claude did not finish within {timeout} seconds", code="agent_timeout"
        ) from exc
    except OSError as exc:
        raise AgentInvocationError(f"could not start claude: {exc}") from exc
    _failure(AgentProvider.CLAUDE, completed)
    try:
        envelope = _object(json.loads(completed.stdout), AgentProvider.CLAUDE)
    except json.JSONDecodeError as exc:
        raise AgentInvocationError(
            f"claude returned invalid JSON: {exc}", code="invalid_agent_output"
        ) from exc
    usage = dict(envelope.get("usage")) if isinstance(envelope.get("usage"), dict) else {}
    if envelope.get("total_cost_usd") is not None:
        usage["estimated_cost_usd"] = envelope["total_cost_usd"]
    return AgentWriteResult(
        AgentProvider.CLAUDE,
        str(envelope.get("result") or "").strip(),
        str(envelope.get("session_id") or ""),
        usage,
    )


def invoke_change(
    provider: AgentProvider,
    cwd: Path,
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 1800,
) -> AgentWriteResult:
    path = executable(provider)
    if path is None:
        raise AgentInvocationError(
            f"{provider.value} is unavailable; {discovery_hint(provider)}",
            code="missing_agent",
        )
    if timeout <= 0:
        raise AgentInvocationError(
            "timeout must be greater than zero", code="invalid_invocation"
        )
    if provider == AgentProvider.CODEX:
        return _invoke_codex_write(path, cwd, prompt, model=model, timeout=timeout)
    return _invoke_claude_write(path, cwd, prompt, model=model, timeout=timeout)
