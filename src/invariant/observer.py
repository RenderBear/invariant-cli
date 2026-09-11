from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from invariant import dashboard
from invariant.errors import Blocked, InvariantError
from invariant.mechanics import audit, config, coordinate, git, governance, receipts, state
from invariant.mechanics.documents import dump_yaml, load_yaml


PROCESS_STALE_SECONDS = 5
SNAPSHOT_INTERVAL_SECONDS = 1.0
EVENT_HEARTBEAT_SECONDS = 15.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProcessPresence:
    """Best-effort local presence for long-running public Invariant commands."""

    def __init__(self, repo: Path, command: str, task: str = "") -> None:
        self.repo = repo
        self.command = command
        self.task = task
        self.pid = os.getpid()
        self.started = _timestamp()
        self.path = coordinate.runtime_root(repo) / "processes" / f"{self.pid}.yml"
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.active = False

    def _write(self) -> None:
        dump_yaml(
            self.path,
            {
                "version": 1,
                "pid": self.pid,
                "command": self.command,
                "task": self.task,
                "started": self.started,
                "heartbeat": _timestamp(),
            },
        )

    def _heartbeat(self) -> None:
        while not self.stop_event.wait(1.0):
            try:
                self._write()
            except (OSError, InvariantError):
                return

    def __enter__(self) -> ProcessPresence:
        try:
            coordinate.ensure_runtime(self.repo)
            self._write()
        except (OSError, InvariantError):
            return self
        self.active = True
        self.thread = threading.Thread(
            target=self._heartbeat,
            name=f"invariant-presence-{self.pid}",
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        if not self.active:
            return
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            # Presence is advisory and must never change a command's outcome.
            pass


def track_process(repo: Path, command: str, task: str = "") -> ProcessPresence:
    return ProcessPresence(repo, command, task)


def _mapping(path: Path, diagnostics: list[str]) -> dict[str, Any] | None:
    try:
        raw = load_yaml(path)
    except InvariantError as exc:
        diagnostics.append(exc.message)
        return None
    if not isinstance(raw, dict):
        diagnostics.append(f"{path}: expected a mapping")
        return None
    return raw


def _scope(receipt: dict[str, Any], name: str) -> list[str]:
    raw = receipt.get("scope")
    values = raw.get(name) if isinstance(raw, dict) else []
    return [str(item) for item in values] if isinstance(values, list) else []


def _task_freshness(repo: Path, receipt: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    target = str(receipt.get("integration_target") or "")
    base = str(receipt.get("integration_head") or "")
    try:
        if receipts.mechanics_digest() != receipt.get("mechanics_digest"):
            reasons.append("CLI mechanics changed")
        if target and receipts.repository_identity(repo, target) != receipt.get("repository"):
            reasons.append("repository identity changed")
        paths = _scope(receipt, "paths")
        interfaces = _scope(receipt, "interfaces")
        domains = _scope(receipt, "domains")
        recorded = (
            receipt.get("governance_snapshot")
            if isinstance(receipt.get("governance_snapshot"), dict)
            else {}
        )
        if governance.context_digest(repo, domains, paths, interfaces) != recorded.get(
            "selected_digest"
        ):
            reasons.append("selected governance changed")
        head = receipts.integration_head(repo, target) if target else ""
        if head != base:
            if "unborn" in {base, head}:
                reasons.append("integration branch birth state changed")
            elif not base or not head or not git.is_ancestor(repo, base, head):
                reasons.append("integration history diverged from the captured ground")
            else:
                current_digest = governance.context_digest(
                    repo, domains, paths, interfaces, head
                )
                if current_digest != recorded.get("integration_digest"):
                    reasons.append("selected governance changed on the integration branch")
                material = governance.material_changes(repo, base, head, domains)
                if material:
                    reasons.append(material[0].removeprefix("MATERIAL-CHANGED: "))
    except InvariantError as exc:
        reasons.append(exc.message.removeprefix("Invariant: "))
    if any("diverged" in reason for reason in reasons):
        return "diverged", reasons
    return ("stale", reasons) if reasons else ("fresh", [])


def _assurance(receipt: dict[str, Any]) -> dict[str, str]:
    raw = receipt.get("assurance")
    if not isinstance(raw, dict):
        return {}
    return {
        name: str(value.get("status") or "unknown")
        for name, value in raw.items()
        if isinstance(value, dict)
    }


def _tasks(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    root = receipts.receipt_root(repo)
    output: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
        raw = _mapping(path, diagnostics)
        if raw is None or raw.get("superseded_by"):
            continue
        lifecycle = raw.get("lifecycle") if isinstance(raw.get("lifecycle"), dict) else {}
        classification = (
            raw.get("change_classification")
            if isinstance(raw.get("change_classification"), dict)
            else {}
        )
        pending = raw.get("hook_requests")
        freshness, stale_reasons = _task_freshness(repo, raw)
        output.append(
            {
                "id": str(raw.get("task") or path.stem),
                "kind": "establishment" if isinstance(raw.get("governance_run"), dict) else "change",
                "stage": str(lifecycle.get("stage") or "briefed"),
                "target": str(raw.get("integration_target") or ""),
                "base": str(raw.get("integration_head") or ""),
                "branch": str(lifecycle.get("branch") or ""),
                "worktree": str(lifecycle.get("worktree") or ""),
                "boundary": str(classification.get("boundary") or "unresolved"),
                "freshness": freshness,
                "stale_reasons": stale_reasons,
                "pending_actions": len(pending) if isinstance(pending, list) else 0,
                "assurance": _assurance(raw),
            }
        )
    return output


def _landed_units(repo: Path, target: str) -> set[str]:
    if not target or not git.resolve(repo, target):
        return set()
    result = git.run(
        [
            "log",
            "--first-parent",
            target,
            "--format=%(trailers:key=Invariant-Unit,valueonly,separator=%x0a)",
        ],
        cwd=repo,
        check=False,
    )
    return set(filter(None, result.stdout.splitlines()))


def _plans(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    root = coordinate.runtime_root(repo) / "plans"
    output: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
        raw = _mapping(path, diagnostics)
        if raw is None:
            continue
        failures: list[str] = []
        try:
            coordinate.validate_plan(repo, path.stem)
        except InvariantError as exc:
            failures = [exc.message, *exc.lines]
        target = str(raw.get("integration_target") or "HEAD")
        landed = _landed_units(repo, target)
        units: list[dict[str, Any]] = []
        for item in raw.get("units", []):
            if not isinstance(item, dict):
                continue
            unit = str(item.get("id") or "")
            dependencies = governance.refs(item.get("dependencies"))
            if unit in landed:
                unit_state = "landed"
            elif (coordinate.runtime_root(repo) / "leases" / f"{unit}.yml").is_file():
                unit_state = "active"
            else:
                unit_state = (
                    "dispatchable" if all(value in landed for value in dependencies) else "waiting"
                )
            units.append(
                {"id": unit, "state": unit_state, "dependencies": dependencies}
            )
        output.append(
            {
                "id": str(raw.get("id") or path.stem),
                "summary": str(raw.get("summary") or raw.get("goal") or ""),
                "valid": not failures,
                "diagnostics": failures,
                "units": units,
            }
        )
    return output


def _leases(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    root = coordinate.runtime_root(repo) / "leases"
    output: list[dict[str, Any]] = []
    now = _now()
    for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
        raw = _mapping(path, diagnostics)
        if raw is None:
            continue
        unit = str(raw.get("unit") or path.stem)
        expires = _parse_timestamp(raw.get("expires"))
        lease_state = "expired" if expires is not None and expires < now else "live"
        freshness = "fresh"
        freshness_detail = ""
        try:
            values = coordinate.lease_fresh(repo, unit)
            freshness_detail = values[0] if values else ""
        except Blocked as exc:
            freshness = "stale"
            freshness_detail = exc.message
        except InvariantError as exc:
            freshness = "invalid"
            freshness_detail = exc.message
        if freshness in {"stale", "invalid"}:
            lease_state = freshness
        output.append(
            {
                "unit": unit,
                "state": lease_state,
                "freshness": freshness,
                "detail": freshness_detail,
                "owner": str(raw.get("owner") or ""),
                "task": str(raw.get("task") or ""),
                "branch": str(raw.get("branch") or ""),
                "expires": str(raw.get("expires") or ""),
                "paths": governance.refs(raw.get("paths")),
                "interfaces": governance.refs(raw.get("interfaces")),
                "governance": governance.refs(raw.get("governance")),
            }
        )
    return output


def _processes(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    root = coordinate.runtime_root(repo) / "processes"
    output: list[dict[str, Any]] = []
    now = _now()
    for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
        raw = _mapping(path, diagnostics)
        if raw is None:
            continue
        try:
            pid = int(raw.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        heartbeat = _parse_timestamp(raw.get("heartbeat"))
        recent = bool(
            heartbeat and (now - heartbeat).total_seconds() <= PROCESS_STALE_SECONDS
        )
        output.append(
            {
                "pid": pid,
                "command": str(raw.get("command") or "unknown"),
                "task": str(raw.get("task") or ""),
                "started": str(raw.get("started") or ""),
                "state": "running" if recent and _pid_alive(pid) else "stale",
            }
        )
    return sorted(output, key=lambda item: (item["state"] != "running", item["pid"]))


def _governance(repo: Path, diagnostics: list[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for kind, relative in governance.RECORD_DIRECTORIES.items():
        root = repo / relative
        for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
            raw = _mapping(path, diagnostics)
            if raw is None:
                continue
            summary = (
                raw.get("responsibility")
                or raw.get("description")
                or raw.get("invariant")
                or raw.get("document")
                or ""
            )
            records.append(
                {
                    "kind": kind,
                    "id": str(raw.get("id") or path.stem),
                    "status": str(raw.get("status") or "active"),
                    "authority": str(raw.get("authority") or ""),
                    "summary": str(summary),
                    "document": str(raw.get("document") or ""),
                    "path": path.relative_to(repo).as_posix(),
                }
            )
    try:
        validation = state.validate(repo)
        valid = validation[-1] in {
            "Invariant state valid",
            "no Invariant state — nothing to validate",
        }
        state_name = "valid" if valid else "invalid"
        state_diagnostics = [] if valid else validation
    except InvariantError as exc:
        state_name = "invalid"
        state_diagnostics = [exc.message, *exc.lines]
    return {
        "state": state_name,
        "diagnostics": state_diagnostics,
        "records": records,
    }


def _evidence_freshness(repo: Path, path: Path) -> tuple[str, str]:
    try:
        values = audit.fresh(repo, path.relative_to(repo).as_posix())
        return "fresh", values[0] if values else ""
    except Blocked as exc:
        return "stale" if exc.code == "stale_evidence" else "diverged", exc.message
    except InvariantError as exc:
        return "invalid", exc.message


def _evidence(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    verification_root = coordinate.runtime_root(repo) / "verifications"
    for path in sorted(verification_root.glob("*.yml")) if verification_root.is_dir() else []:
        raw = _mapping(path, diagnostics)
        if raw is None:
            continue
        command = raw.get("command")
        output.append(
            {
                "id": str(raw.get("evidence_id") or path.stem),
                "kind": "verification",
                "status": str(raw.get("status") or "unknown"),
                "summary": " ".join(str(item) for item in command) if isinstance(command, list) else "",
                "locator": str(raw.get("locator") or ""),
                "tree": str(raw.get("tree") or ""),
                "base": str(raw.get("base") or ""),
                "captured_at": str(raw.get("captured_at") or ""),
                "duration_ms": raw.get("duration_ms"),
            }
        )
    def append_task_evidence(task_path: Path, task_id: str) -> None:
        if not task_path.is_dir():
            return
        evidence_root = task_path / "evidence"
        for path in sorted(evidence_root.glob("*.yml")) if evidence_root.is_dir() else []:
            raw = _mapping(path, diagnostics)
            if raw is None:
                continue
            output.append(
                {
                    "id": str(raw.get("evidence_id") or path.stem),
                    "kind": str(raw.get("kind") or "candidate"),
                    "status": str(raw.get("status") or "recorded"),
                    "summary": str(raw.get("summary") or raw.get("observation") or ""),
                    "task": task_id,
                    "tree": str(raw.get("tree") or ""),
                    "ground": str(raw.get("ground") or raw.get("base") or ""),
                    "captured_at": str(
                        raw.get("captured_at")
                        or _timestamp(
                            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                        )
                    ),
                }
            )
        review_paths = [task_path / "candidate-review.yml"]
        rejection_root = task_path / "rejected-reviews"
        if rejection_root.is_dir():
            review_paths.extend(sorted(rejection_root.glob("*.yml")))
        for path in review_paths:
            if not path.is_file():
                continue
            raw = _mapping(path, diagnostics)
            if raw is None:
                continue
            output.append(
                {
                    "id": str(raw.get("review_id") or path.stem),
                    "kind": "review",
                    "status": str(raw.get("verdict") or "recorded"),
                    "summary": str(raw.get("summary") or ""),
                    "task": task_id,
                    "tree": str(raw.get("candidate_tree") or ""),
                    "captured_at": str(
                        raw.get("created_at")
                        or _timestamp(
                            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                        )
                    ),
                }
            )

    active_tasks = receipts.task_root(repo, "_").parent
    for task_path in sorted(active_tasks.iterdir()) if active_tasks.is_dir() else []:
        append_task_evidence(task_path, task_path.name)
    history_tasks = coordinate.runtime_root(repo) / "history" / "tasks"
    for task_path in (
        sorted(history_tasks.glob("*/*")) if history_tasks.is_dir() else []
    ):
        append_task_evidence(task_path, task_path.parent.name)
    for kind, directory in (
        ("audit", repo / ".invariant" / "audits"),
        ("discovery", repo / ".invariant" / "discoveries"),
    ):
        for path in sorted(directory.glob("*.yml")) if directory.is_dir() else []:
            raw = _mapping(path, diagnostics)
            if raw is None:
                continue
            freshness, detail = _evidence_freshness(repo, path)
            findings = raw.get("findings")
            summary = str(raw.get("observation") or raw.get("summary") or "")
            if not summary and isinstance(findings, list):
                summary = f"{len(findings)} audit finding{'s' if len(findings) != 1 else ''}"
            output.append(
                {
                    "id": str(raw.get("id") or path.stem),
                    "kind": kind,
                    "status": str(raw.get("status") or "recorded"),
                    "freshness": freshness,
                    "summary": summary or detail,
                    "tree": str(raw.get("tree") or ""),
                    "ground": str(raw.get("ground") or ""),
                    "captured_at": str(raw.get("created_at") or ""),
                }
            )
    return sorted(
        output,
        key=lambda item: (str(item.get("captured_at") or ""), str(item.get("id") or "")),
        reverse=True,
    )[:100]


def _history(repo: Path, diagnostics: list[str]) -> list[dict[str, Any]]:
    root = coordinate.runtime_root(repo) / "history" / "tasks"
    paths = sorted(
        root.glob("*/*/summary.yml") if root.is_dir() else [],
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )[:20]
    output: list[dict[str, Any]] = []
    for path in paths:
        raw = _mapping(path, diagnostics)
        if raw is None:
            continue
        landing = raw.get("landing") if isinstance(raw.get("landing"), dict) else {}
        boundary = raw.get("boundary") if isinstance(raw.get("boundary"), dict) else {}
        output.append(
            {
                "task": str(raw.get("task") or path.parents[1].name),
                "status": "completed",
                "commit": str(
                    landing.get("commit")
                    or raw.get("completed_commit")
                    or raw.get("commit")
                    or path.parent.name
                ),
                "boundary": str(
                    boundary.get("final")
                    or raw.get("resolved_boundary")
                    or ""
                ),
            }
        )
    return output


def build_snapshot(repo: Path) -> dict[str, Any]:
    diagnostics: list[str] = []
    resolved = config.resolve(repo)
    repository = {
        "name": repo.name,
        "path": str(repo),
        "branch": git.current_branch(repo) or "detached",
        "head": git.resolve(repo, "HEAD") or "unborn",
        "integration_branch": resolved.integration_branch,
        "authority": resolved.authority,
        "execution": resolved.execution,
    }
    governance_state = _governance(repo, diagnostics)
    repository["state"] = governance_state["state"]
    payload: dict[str, Any] = {
        "version": 1,
        "repository": repository,
        "processes": _processes(repo, diagnostics),
        "tasks": _tasks(repo, diagnostics),
        "plans": _plans(repo, diagnostics),
        "leases": _leases(repo, diagnostics),
        "governance": governance_state,
        "evidence": _evidence(repo, diagnostics),
        "history": _history(repo, diagnostics),
        "diagnostics": diagnostics,
    }
    revision = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**payload, "revision": revision, "observed_at": _timestamp()}


def _failed_snapshot(previous: dict[str, Any], error: Exception) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in previous.items()
        if key not in {"revision", "observed_at"}
    }
    repository = dict(payload.get("repository", {}))
    repository["state"] = "invalid"
    payload["repository"] = repository
    message = (
        error.message
        if isinstance(error, InvariantError)
        else f"{type(error).__name__}: {error}"
    )
    payload["diagnostics"] = [message]
    revision = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**payload, "revision": revision, "observed_at": _timestamp()}


class SnapshotStore:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.condition = threading.Condition()
        self.snapshot = build_snapshot(repo)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._poll,
            name="invariant-observer",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=3)

    def current(self) -> dict[str, Any]:
        with self.condition:
            return self.snapshot

    def wait(self, revision: str, timeout: float) -> dict[str, Any]:
        with self.condition:
            if self.snapshot["revision"] == revision:
                self.condition.wait(timeout)
            return self.snapshot

    def _poll(self) -> None:
        while not self.stop_event.wait(SNAPSHOT_INTERVAL_SECONDS):
            try:
                candidate = build_snapshot(self.repo)
            except Exception as exc:
                candidate = _failed_snapshot(self.snapshot, exc)
            with self.condition:
                if candidate["revision"] != self.snapshot["revision"]:
                    self.snapshot = candidate
                    self.condition.notify_all()


class _ObservationHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True

    def __init__(self, address: tuple[str, int], store: SnapshotStore) -> None:
        self.store = store
        self.stopping = threading.Event()
        super().__init__(address, _RequestHandler)

    def handle_error(self, request: object, client_address: object) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class _RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _ObservationHTTPServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _headers(self, content_type: str, length: int | None = None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self'; "
            "script-src 'self'; style-src 'self'; frame-ancestors 'none'",
        )
        if length is not None:
            self.send_header("Content-Length", str(length))

    def _send(self, status: HTTPStatus, content_type: str, body: bytes, *, head: bool) -> None:
        self.send_response(status)
        self._headers(content_type, len(body))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, value: dict[str, Any], *, head: bool = False) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self._send(HTTPStatus.OK, "application/json; charset=utf-8", body, head=head)

    def _events(self, *, head: bool) -> None:
        self.send_response(HTTPStatus.OK)
        self._headers("text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        if head:
            return
        self.close_connection = True
        revision = ""
        try:
            while not self.server.stopping.is_set():
                snapshot = self.server.store.wait(revision, EVENT_HEARTBEAT_SECONDS)
                if self.server.stopping.is_set():
                    return
                current = str(snapshot["revision"])
                if current != revision:
                    body = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
                    self.wfile.write(
                        f"id: {current}\nevent: snapshot\ndata: {body}\n\n".encode("utf-8")
                    )
                    revision = current
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _get(self, *, head: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                dashboard.HTML.encode("utf-8"),
                head=head,
            )
        elif path == "/assets/app.css":
            self._send(
                HTTPStatus.OK,
                "text/css; charset=utf-8",
                dashboard.CSS.encode("utf-8"),
                head=head,
            )
        elif path == "/assets/app.js":
            self._send(
                HTTPStatus.OK,
                "text/javascript; charset=utf-8",
                dashboard.JS.encode("utf-8"),
                head=head,
            )
        elif path == "/api/v1/snapshot":
            self._json(self.server.store.current(), head=head)
        elif path == "/api/v1/events":
            self._events(head=head)
        elif path == "/healthz":
            snapshot = self.server.store.current()
            self._json({"status": "ok", "revision": snapshot["revision"]}, head=head)
        elif path == "/favicon.ico":
            self._send(HTTPStatus.NO_CONTENT, "image/x-icon", b"", head=head)
        else:
            self._send(
                HTTPStatus.NOT_FOUND,
                "application/json; charset=utf-8",
                b'{"error":"not_found"}',
                head=head,
            )

    def do_GET(self) -> None:
        self._get(head=False)

    def do_HEAD(self) -> None:
        self._get(head=True)

    def _method_not_allowed(self) -> None:
        body = b'{"error":"method_not_allowed"}'
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._headers("application/json; charset=utf-8", len(body))
        self.send_header("Allow", "GET, HEAD")
        self.end_headers()
        self.wfile.write(body)

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


@contextmanager
def running_server(repo: Path, port: int) -> Iterator[None]:
    """Run the observation server for the lifetime of its owning console session."""

    store = SnapshotStore(repo)
    try:
        server = _ObservationHTTPServer(("127.0.0.1", port), store)
    except OSError as exc:
        raise InvariantError(
            f"Invariant: cannot start the local server on 127.0.0.1:{port}: {exc}",
            code="server_unavailable",
        ) from exc
    store.start()
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.5},
        name="invariant-observation-server",
    )
    thread.start()
    try:
        yield
    finally:
        server.stopping.set()
        store.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
