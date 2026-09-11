from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

import yaml

from lifecycle_support import CLI, git, invariant, repository


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _cli(repo: Path, home: Path, *arguments: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [str(CLI), "--format", "json", *arguments],
        cwd=repo,
        env={**os.environ, "INVARIANT_HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, json.loads(completed.stdout)


def _wait_for_json(url: str, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"host exited {process.returncode}: stdout={stdout!r} stderr={stderr!r}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"host did not become ready: {last_error}")


def _post(url: str, value: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(value).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def _next_snapshot(stream: BinaryIO) -> dict:
    data = ""
    while True:
        line = stream.readline().decode("utf-8")
        if not line:
            raise AssertionError("SSE stream ended before a snapshot event")
        if line.startswith("data: "):
            data = line.removeprefix("data: ").strip()
        if line == "\n" and data:
            return json.loads(data)


def test_projects_and_sessions_are_machine_local_cli_state(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    home = tmp_path / "invariant-home"

    config = yaml.safe_load((repo / ".invariant" / "config.yml").read_text())
    assert "server" not in config
    code, payload = invariant(repo, "set", "server.port", "43123")
    assert code == 2
    assert payload["diagnostics"][0]["code"] == "invalid_config_key"

    code, payload = _cli(repo, home, "session", "new", "Authentication redesign", "--mode", "change")
    assert code == 0, payload
    session = payload["result"]["session"]
    code, payload = _cli(repo, home, "project", "list")
    assert code == 0, payload
    project = next(item for item in payload["result"]["projects"] if item["path"] == str(repo))
    assert session["project_id"] == project["id"]
    assert git(repo, "status", "--porcelain") == ""
    assert session["theme"] == "Authentication redesign"
    assert session["mode"] == "change"
    assert "provider_session_id" not in session

    code, payload = _cli(repo, home, "session", "list")
    assert code == 0, payload
    assert [item["id"] for item in payload["result"]["sessions"]] == [session["id"]]
    assert (home / "workspace.yml").is_file()
    assert git(repo, "status", "--porcelain") == ""


def test_per_user_host_is_a_read_only_state_and_session_explorer(tmp_path: Path) -> None:
    first_repo = repository(tmp_path / "first")
    second_repo = repository(tmp_path / "second")
    home = tmp_path / "invariant-home"
    code, payload = _cli(first_repo, home, "session", "new", "Host architecture", "--mode", "ask")
    assert code == 0, payload
    session = payload["result"]["session"]
    port = _available_port()
    process = subprocess.Popen(
        [
            str(CLI),
            "serve",
            "--port",
            str(port),
            "--project",
            str(first_repo),
            "--project",
            str(second_repo),
        ],
        cwd=first_repo,
        env={
            **os.environ,
            "INVARIANT_HOME": str(home),
            "PYTHONUNBUFFERED": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    stream = None
    try:
        state = _wait_for_json(f"{base_url}/host/v1/state", process)
        assert [item["name"] for item in state["projects"]] == ["second", "first"]
        assert "csrf_token" not in state
        first = next(item for item in state["projects"] if item["path"] == str(first_repo))

        duplicate = subprocess.run(
            [str(CLI), "serve", "--port", str(_available_port())],
            cwd=first_repo,
            env={**os.environ, "INVARIANT_HOME": str(home)},
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert duplicate.returncode == 2
        assert "already running for this OS user" in duplicate.stderr

        with urllib.request.urlopen(f"{base_url}/", timeout=2) as response:
            page = response.read().decode("utf-8")
            assert response.headers["Content-Security-Policy"]
            assert "Invariant · State explorer" in page
            assert 'aria-label="Project folders and session files"' in page
            assert "Sessions appear as files and open as read-only logs." in page
            assert 'id="composer"' not in page
            assert "<form" not in page

        code, payload = _post(
            f"{base_url}/host/v1/projects/{first['id']}/sessions",
            {"theme": "Host architecture", "mode": "ask"},
        )
        assert code == 405
        assert payload["error"] == "method_not_allowed"

        code, payload = _post(
            f"{base_url}/host/v1/sessions/{session['id']}/turns",
            {"message": "What owns the server?"},
        )
        assert code == 405
        assert payload["error"] == "method_not_allowed"

        with urllib.request.urlopen(f"{base_url}/host/v1/state", timeout=2) as response:
            refreshed = json.load(response)
        summary = next(item for item in refreshed["sessions"] if item["id"] == session["id"])
        assert summary["message_count"] == 0
        assert "messages" not in summary

        with urllib.request.urlopen(
            f"{base_url}/host/v1/sessions/{session['id']}", timeout=2
        ) as response:
            opened = json.load(response)
        assert opened["session"]["theme"] == "Host architecture"
        assert opened["session"]["messages"] == []

        with urllib.request.urlopen(
            f"{base_url}/host/v1/projects/{first['id']}/snapshot", timeout=2
        ) as response:
            snapshot = json.load(response)
        assert snapshot["repository"]["name"] == "first"

        request = urllib.request.Request(f"{base_url}/api/v1/snapshot")
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("multi-project observer route did not require a project")

        stream = urllib.request.urlopen(
            f"{base_url}/host/v1/projects/{first['id']}/events", timeout=5
        )
        before = _next_snapshot(stream)
        code, payload = invariant(
            first_repo,
            "task",
            "begin",
            "host-observed-change",
            "--goal",
            "Emit a changed host snapshot.",
            "--boundary",
            "no-record",
        )
        assert code == 0, payload
        after = _next_snapshot(stream)
        assert after["revision"] != before["revision"]
        assert [item["id"] for item in after["tasks"]] == ["host-observed-change"]
    finally:
        if stream is not None:
            stream.close()
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert f"http://127.0.0.1:{port}" in stdout

    code, payload = _cli(first_repo, home, "session", "show", session["id"])
    assert code == 0, payload
    assert payload["result"]["session"]["messages"] == []
