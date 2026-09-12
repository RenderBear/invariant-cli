from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from invariant.errors import InvariantError
from invariant.harness import preferences
from invariant.mechanics import config, git


WORKSPACE_VERSION = 1
DEFAULT_HOST_PORT = 3000
_PROCESS_LOCK = threading.RLock()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def workspace_path() -> Path:
    return preferences.global_root() / "workspace.yml"


def _empty() -> dict[str, Any]:
    return {"version": WORKSPACE_VERSION, "projects": [], "sessions": []}


def _acquire(handle: Any, *, nonblocking: bool = False) -> bool:
    try:
        import fcntl

        mode = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        try:
            fcntl.flock(handle.fileno(), mode)
        except BlockingIOError:
            return False
        return True
    except ImportError:  # pragma: no cover - exercised on Windows.
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        mode = msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK
        try:
            msvcrt.locking(handle.fileno(), mode, 1)
        except OSError:
            if nonblocking:
                return False
            raise
        return True


def _release(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except ImportError:  # pragma: no cover - exercised on Windows.
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def _file_lock() -> Iterator[None]:
    root = preferences.global_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "workspace.lock"
    with _PROCESS_LOCK, path.open("a+b") as handle:
        _acquire(handle)
        try:
            yield
        finally:
            _release(handle)


def _load_unlocked() -> dict[str, Any]:
    path = workspace_path()
    if not path.is_file():
        return _empty()
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InvariantError(
            f"Invariant: invalid local workspace state in {path}: {exc}",
            code="invalid_workspace",
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != WORKSPACE_VERSION
        or not isinstance(value.get("projects"), list)
        or not isinstance(value.get("sessions"), list)
    ):
        raise InvariantError(
            f"Invariant: local workspace state in {path} must declare version: {WORKSPACE_VERSION}",
            code="invalid_workspace",
        )
    return value


def _save_unlocked(value: dict[str, Any]) -> None:
    path = workspace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, pending_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    pending = Path(pending_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(value, handle, sort_keys=False, allow_unicode=True, width=100)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def revision() -> int:
    """A cheap change marker for the workspace file: its size and modification time."""

    try:
        stat = workspace_path().stat()
    except OSError:
        return 0
    return stat.st_mtime_ns ^ (stat.st_size << 1)


def _read() -> dict[str, Any]:
    with _file_lock():
        return _load_unlocked()


def _change(operation: Any) -> Any:
    with _file_lock():
        value = _load_unlocked()
        result = operation(value)
        _save_unlocked(value)
        return result


def _project_view(project: dict[str, Any], sessions: list[dict[str, Any]]) -> dict[str, Any]:
    path = Path(str(project.get("path") or ""))
    available = path.is_dir()
    initialized = available and config.initialized(path)
    return {
        "id": str(project.get("id") or ""),
        "name": str(project.get("name") or path.name),
        "path": str(path),
        "available": available,
        "initialized": initialized,
        "sessions": sum(1 for session in sessions if session.get("project_id") == project.get("id")),
        "added_at": str(project.get("added_at") or ""),
        "last_opened_at": str(project.get("last_opened_at") or ""),
    }


def _session_view(session: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in session.items()
        if key != "provider_session_id"
    } | {"live": session_presence(str(session.get("id") or ""))}


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages")
    return {
        key: value
        for key, value in session.items()
        if key not in {"provider_session_id", "messages"}
    } | {
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "live": session_presence(str(session.get("id") or "")),
    }


PRESENCE_STALE_SECONDS = 300


def _presence_path(identifier: str) -> Path:
    return preferences.global_root() / "sessions" / f"{identifier}.live"


def mark_session_live(identifier: str, *, surface: str) -> None:
    """Record that a console on this machine currently holds the session."""

    path = _presence_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": os.getpid(), "surface": surface, "updated_at": _timestamp()}),
        encoding="utf-8",
    )


def clear_session_live(identifier: str) -> None:
    _presence_path(identifier).unlink(missing_ok=True)


def session_presence(identifier: str) -> dict[str, Any] | None:
    """The console holding the session right now, or None. Presence is a hint, never authority."""

    path = _presence_path(identifier)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    pid = raw.get("pid")
    updated = raw.get("updated_at")
    try:
        os.kill(int(pid), 0)
        stamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except (OSError, TypeError, ValueError):
        return None
    if (datetime.now(timezone.utc) - stamp).total_seconds() > PRESENCE_STALE_SECONDS:
        return None
    return {"pid": int(pid), "surface": str(raw.get("surface") or "console"), "since": str(updated)}


def add_project(folder: Path | str) -> dict[str, Any]:
    repo = git.root(folder)
    config.require_initialized(repo)
    canonical = str(repo)
    common_dir = str(git.common_dir(repo))

    def operation(value: dict[str, Any]) -> dict[str, Any]:
        projects = value["projects"]
        sessions = value["sessions"]
        existing = next(
            (item for item in projects if isinstance(item, dict) and item.get("path") == canonical),
            None,
        )
        now = _timestamp()
        if existing is None:
            identifiers = {str(item.get("id")) for item in projects if isinstance(item, dict)}
            identifier = ""
            while not identifier or identifier in identifiers:
                identifier = f"p-{secrets.token_hex(5)}"
            existing = {
                "id": identifier,
                "name": repo.name,
                "path": canonical,
                "git_common_dir": common_dir,
                "added_at": now,
                "last_opened_at": now,
            }
            projects.append(existing)
        else:
            if existing.get("git_common_dir") != common_dir:
                raise InvariantError(
                    "Invariant: registered project "
                    f"'{existing.get('id')}' now resolves to a different Git repository",
                    code="project_unavailable",
                    lines=[
                        f"FOLDER: {canonical}",
                        f"NEXT: remove project {existing.get('id')}, then register the folder again",
                    ],
                )
            existing["name"] = repo.name
            existing["last_opened_at"] = now
        return _project_view(existing, sessions)

    return _change(operation)


def list_projects() -> list[dict[str, Any]]:
    value = _read()
    projects = [item for item in value["projects"] if isinstance(item, dict)]
    sessions = [item for item in value["sessions"] if isinstance(item, dict)]
    return sorted(
        (_project_view(item, sessions) for item in projects),
        key=lambda item: (item["last_opened_at"], item["name"].lower()),
        reverse=True,
    )


def project(identifier: str) -> dict[str, Any]:
    value = _read()
    item = next(
        (
            candidate
            for candidate in value["projects"]
            if isinstance(candidate, dict) and candidate.get("id") == identifier
        ),
        None,
    )
    if item is None:
        raise InvariantError(
            f"Invariant: no registered project '{identifier}'",
            code="missing_project",
        )
    return _project_view(item, [x for x in value["sessions"] if isinstance(x, dict)])


def project_repo(identifier: str) -> Path:
    value = _read()
    selected = next(
        (
            candidate
            for candidate in value["projects"]
            if isinstance(candidate, dict) and candidate.get("id") == identifier
        ),
        None,
    )
    if selected is None:
        raise InvariantError(
            f"Invariant: no registered project '{identifier}'",
            code="missing_project",
        )
    path = Path(str(selected.get("path") or ""))
    if not path.is_dir() or not config.initialized(path):
        raise InvariantError(
            f"Invariant: project '{identifier}' is unavailable at {path}",
            code="project_unavailable",
        )
    try:
        repo = git.root(path)
    except InvariantError as exc:
        raise InvariantError(
            f"Invariant: project '{identifier}' is unavailable at {path}",
            code="project_unavailable",
        ) from exc
    expected_common_dir = str(selected.get("git_common_dir") or "")
    if (
        repo != path.resolve()
        or not expected_common_dir
        or str(git.common_dir(repo)) != expected_common_dir
    ):
        raise InvariantError(
            f"Invariant: project '{identifier}' no longer resolves to {path}",
            code="project_unavailable",
        )
    return repo


def remove_project(identifier: str) -> dict[str, Any]:
    def operation(value: dict[str, Any]) -> dict[str, Any]:
        item = next(
            (
                candidate
                for candidate in value["projects"]
                if isinstance(candidate, dict) and candidate.get("id") == identifier
            ),
            None,
        )
        if item is None:
            raise InvariantError(
                f"Invariant: no registered project '{identifier}'",
                code="missing_project",
            )
        value["projects"] = [candidate for candidate in value["projects"] if candidate is not item]
        removed_sessions = [
            candidate
            for candidate in value["sessions"]
            if isinstance(candidate, dict) and candidate.get("project_id") == identifier
        ]
        value["sessions"] = [
            candidate
            for candidate in value["sessions"]
            if candidate not in removed_sessions
        ]
        return {
            "id": identifier,
            "name": str(item.get("name") or ""),
            "path": str(item.get("path") or ""),
            "removed_sessions": len(removed_sessions),
        }

    return _change(operation)


def _theme(value: str) -> str:
    theme = " ".join(value.strip().split())
    if not theme or len(theme) > 80:
        raise InvariantError(
            "Invariant: a session theme must contain 1 through 80 characters",
            code="invalid_session_theme",
        )
    return theme


def new_session(
    repo: Path,
    theme: str,
    *,
    mode: str = "change",
    provider: str = "",
) -> dict[str, Any]:
    if mode not in {"ask", "change"}:
        raise InvariantError(
            "Invariant: mode must be ask or change",
            code="invalid_session_mode",
        )
    selected_project = add_project(repo)
    title = _theme(theme)

    def operation(value: dict[str, Any]) -> dict[str, Any]:
        if not any(
            isinstance(item, dict) and item.get("id") == selected_project["id"]
            for item in value["projects"]
        ):
            raise InvariantError(
                f"Invariant: no registered project '{selected_project['id']}'",
                code="missing_project",
            )
        identifiers = {
            str(item.get("id")) for item in value["sessions"] if isinstance(item, dict)
        }
        identifier = ""
        while not identifier or identifier in identifiers:
            identifier = f"s-{secrets.token_hex(5)}"
        now = _timestamp()
        item = {
            "id": identifier,
            "project_id": selected_project["id"],
            "theme": title,
            "mode": mode,
            "provider": provider,
            "provider_session_id": "",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        value["sessions"].append(item)
        return _session_view(item)

    return _change(operation)


def list_sessions(*, project_id: str | None = None) -> list[dict[str, Any]]:
    value = _read()
    sessions = [item for item in value["sessions"] if isinstance(item, dict)]
    if project_id is not None:
        if not any(
            isinstance(item, dict) and item.get("id") == project_id
            for item in value["projects"]
        ):
            raise InvariantError(
                f"Invariant: no registered project '{project_id}'",
                code="missing_project",
            )
        sessions = [item for item in sessions if item.get("project_id") == project_id]
    return sorted(
        (_session_view(item) for item in sessions),
        key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")),
        reverse=True,
    )


def session(identifier: str) -> dict[str, Any]:
    value = _read()
    item = next(
        (
            candidate
            for candidate in value["sessions"]
            if isinstance(candidate, dict) and candidate.get("id") == identifier
        ),
        None,
    )
    if item is None:
        raise InvariantError(
            f"Invariant: no session '{identifier}'",
            code="missing_session",
        )
    return _session_view(item)


def session_private(identifier: str) -> dict[str, Any]:
    value = _read()
    item = next(
        (
            candidate
            for candidate in value["sessions"]
            if isinstance(candidate, dict) and candidate.get("id") == identifier
        ),
        None,
    )
    if item is None:
        raise InvariantError(
            f"Invariant: no session '{identifier}'",
            code="missing_session",
        )
    return dict(item)


def session_repo(identifier: str) -> Path:
    return project_repo(str(session(identifier)["project_id"]))


def require_session_project(identifier: str, repo: Path) -> dict[str, Any]:
    item = session(identifier)
    selected = project(str(item["project_id"]))
    selected_repo = project_repo(str(item["project_id"]))
    if selected_repo != repo.resolve():
        raise InvariantError(
            f"Invariant: session '{identifier}' belongs to project '{selected['name']}'",
            code="missing_session",
        )
    return item


def update_session(
    identifier: str,
    *,
    mode: str | None = None,
    provider: str | None = None,
    provider_session_id: str | None = None,
    pending_change: str | None = None,
    pending_action: str | None = None,
) -> dict[str, Any]:
    if mode is not None and mode not in {"ask", "change"}:
        raise InvariantError("Invariant: mode must be ask or change", code="invalid_session_mode")

    def operation(value: dict[str, Any]) -> dict[str, Any]:
        item = next(
            (
                candidate
                for candidate in value["sessions"]
                if isinstance(candidate, dict) and candidate.get("id") == identifier
            ),
            None,
        )
        if item is None:
            raise InvariantError(
                f"Invariant: no session '{identifier}'",
                code="missing_session",
            )
        if mode is not None:
            item["mode"] = mode
        if provider is not None:
            item["provider"] = provider
        if provider_session_id is not None:
            item["provider_session_id"] = provider_session_id
        if pending_change is not None:
            item["pending_change"] = pending_change
        if pending_action is not None:
            item["pending_action"] = pending_action
        item["updated_at"] = _timestamp()
        return _session_view(item)

    return _change(operation)


def append_message(
    identifier: str,
    role: str,
    content: str,
    *,
    state: str = "complete",
    action: str = "",
) -> dict[str, Any]:
    if role not in {"user", "assistant", "system"}:
        raise InvariantError("Invariant: invalid session message role", code="invalid_workspace")

    def operation(value: dict[str, Any]) -> dict[str, Any]:
        item = next(
            (
                candidate
                for candidate in value["sessions"]
                if isinstance(candidate, dict) and candidate.get("id") == identifier
            ),
            None,
        )
        if item is None:
            raise InvariantError(
                f"Invariant: no session '{identifier}'",
                code="missing_session",
            )
        now = _timestamp()
        message = {
            "id": f"m-{secrets.token_hex(6)}",
            "role": role,
            "content": content,
            "state": state,
            "created_at": now,
        }
        if action:
            message["action"] = action
        messages = item.setdefault("messages", [])
        if not isinstance(messages, list):
            raise InvariantError("Invariant: invalid session messages", code="invalid_workspace")
        messages.append(message)
        item["updated_at"] = now
        return dict(message)

    return _change(operation)


@contextmanager
def session_lock(identifier: str) -> Iterator[None]:
    root = preferences.global_root() / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identifier}.lock"
    with path.open("a+b") as handle:
        _acquire(handle)
        try:
            yield
        finally:
            _release(handle)


@contextmanager
def host_instance_lock() -> Iterator[None]:
    root = preferences.global_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "host.lock"
    with path.open("a+b") as handle:
        if not _acquire(handle, nonblocking=True):
            raise InvariantError(
                "Invariant: a local host is already running for this OS user",
                code="host_unavailable",
            )
        try:
            yield
        finally:
            _release(handle)


def snapshot() -> dict[str, Any]:
    value = _read()
    projects = [item for item in value["projects"] if isinstance(item, dict)]
    sessions = [item for item in value["sessions"] if isinstance(item, dict)]
    return {
        "version": WORKSPACE_VERSION,
        "projects": sorted(
            (_project_view(item, sessions) for item in projects),
            key=lambda item: (item["last_opened_at"], item["name"].lower()),
            reverse=True,
        ),
        "sessions": sorted(
            (_session_summary(item) for item in sessions),
            key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")),
            reverse=True,
        ),
    }
