from __future__ import annotations

import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from invariant import dashboard, workspace
from invariant.errors import InvariantError
from invariant.observer import (
    EVENT_HEARTBEAT_SECONDS,
    SNAPSHOT_INTERVAL_SECONDS,
    SnapshotStore,
    build_snapshot,
)


def _public_error(error: Exception) -> tuple[HTTPStatus, dict[str, Any]]:
    if isinstance(error, InvariantError):
        status = {
            "missing_project": HTTPStatus.NOT_FOUND,
            "missing_session": HTTPStatus.NOT_FOUND,
            "project_unavailable": HTTPStatus.CONFLICT,
        }.get(error.code, HTTPStatus.BAD_REQUEST)
        return status, {"error": error.code, "message": error.message, "details": error.lines}
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "error": "internal_error",
        "message": f"Invariant: internal host failure — {type(error).__name__}",
    }


class WorkspaceHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        self.stopping = threading.Event()
        self._stores: dict[str, SnapshotStore] = {}
        self._store_references: dict[str, int] = {}
        self._recent: dict[str, tuple[Path, dict[str, Any], float, float]] = {}
        self._stores_lock = threading.Lock()
        super().__init__(address, WorkspaceRequestHandler)

    def snapshot_store(self, project_id: str) -> SnapshotStore:
        repo = workspace.project_repo(project_id)
        with self._stores_lock:
            store = self._stores.get(project_id)
            if store is None or store.repo != repo:
                if store is not None:
                    store.stop()
                store = SnapshotStore(repo)
                store.start()
                self._stores[project_id] = store
                self._store_references[project_id] = 0
            self._store_references[project_id] += 1
            return store

    def release_snapshot_store(self, project_id: str) -> None:
        store: SnapshotStore | None = None
        with self._stores_lock:
            if project_id not in self._stores:
                return
            references = self._store_references.get(project_id, 1) - 1
            if references > 0:
                self._store_references[project_id] = references
                return
            store = self._stores.pop(project_id)
            self._store_references.pop(project_id, None)
        store.stop()

    def project_snapshot(self, project_id: str) -> dict[str, Any]:
        """Serve a snapshot without starting an observer for a one-off read.

        A live store (an events subscriber) is authoritative. Otherwise the last built
        snapshot is reused while it is younger than the longer of the poll interval and the
        time its own build took, so an expensive repository is never rebuilt per request.
        """

        repo = workspace.project_repo(project_id)
        with self._stores_lock:
            store = self._stores.get(project_id)
            if store is not None and store.repo == repo:
                return store.current()
            recent = self._recent.get(project_id)
        if recent is not None:
            cached_repo, snapshot, built_at, build_seconds = recent
            if cached_repo == repo and time.monotonic() - built_at < max(
                SNAPSHOT_INTERVAL_SECONDS, build_seconds
            ):
                return snapshot
        started = time.monotonic()
        snapshot = build_snapshot(repo)
        with self._stores_lock:
            self._recent[project_id] = (repo, snapshot, started, time.monotonic() - started)
        return snapshot

    def stop_stores(self) -> None:
        self.stopping.set()
        with self._stores_lock:
            stores = list(self._stores.values())
            self._stores.clear()
            self._store_references.clear()
        for store in stores:
            store.stop()

    def handle_error(self, request: object, client_address: object) -> None:
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class WorkspaceRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: WorkspaceHTTPServer

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
            "script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'",
        )
        if length is not None:
            self.send_header("Content-Length", str(length))

    def _send(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        *,
        head: bool = False,
    ) -> None:
        self.send_response(status)
        self._headers(content_type, len(body))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(
        self,
        value: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
        head: bool = False,
    ) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, head=head)

    def _trusted_host(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _workspace_state(self) -> dict[str, Any]:
        return workspace.snapshot()

    def _project_from_query(self) -> str:
        query = parse_qs(urlsplit(self.path).query)
        selected = query.get("project", [])
        if selected:
            return selected[0]
        projects = workspace.list_projects()
        if len(projects) == 1:
            return str(projects[0]["id"])
        raise InvariantError(
            "Invariant: choose a registered project with ?project=<id>",
            code="missing_project",
        )

    def _events(self, project_id: str, *, head: bool) -> None:
        store = self.server.snapshot_store(project_id)
        try:
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
                    snapshot = store.wait(revision, EVENT_HEARTBEAT_SECONDS)
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
        finally:
            self.server.release_snapshot_store(project_id)

    def _get(self, *, head: bool) -> None:
        if not self._trusted_host():
            self._json(
                {"error": "host_forbidden", "message": "Invariant: untrusted Host header"},
                status=HTTPStatus.FORBIDDEN,
                head=head,
            )
            return
        path = urlsplit(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
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
            elif path == "/host/v1/state":
                self._json(self._workspace_state(), head=head)
            elif len(parts) == 4 and parts[:3] == ["host", "v1", "sessions"]:
                self._json({"session": workspace.session(parts[3])}, head=head)
            elif len(parts) == 5 and parts[:3] == ["host", "v1", "projects"] and parts[4] == "snapshot":
                self._json(self.server.project_snapshot(parts[3]), head=head)
            elif len(parts) == 5 and parts[:3] == ["host", "v1", "projects"] and parts[4] == "events":
                self._events(parts[3], head=head)
            elif path == "/api/v1/snapshot":
                self._json(self.server.project_snapshot(self._project_from_query()), head=head)
            elif path == "/api/v1/events":
                self._events(self._project_from_query(), head=head)
            elif path == "/healthz":
                self._json(
                    {"status": "ok", "projects": len(workspace.list_projects())},
                    head=head,
                )
            elif path == "/favicon.ico":
                self._send(HTTPStatus.NO_CONTENT, "image/x-icon", b"", head=head)
            else:
                self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND, head=head)
        except Exception as exc:
            status, payload = _public_error(exc)
            self._json(payload, status=status, head=head)

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


def serve(port: int = workspace.DEFAULT_HOST_PORT) -> None:
    with workspace.host_instance_lock():
        try:
            server = WorkspaceHTTPServer(("127.0.0.1", port))
        except OSError as exc:
            raise InvariantError(
                f"Invariant: cannot start the local host on 127.0.0.1:{port}: {exc}",
                code="host_unavailable",
            ) from exc
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop_stores()
            server.server_close()
