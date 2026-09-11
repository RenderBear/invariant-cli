from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO

import yaml

from lifecycle_support import CLI, git, implement, invariant, repository


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _fake_codex(path: Path) -> Path:
    executable = path / "codex"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  echo 'codex-cli server-test'\n"
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _wait_for_json(url: str, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"server exited {process.returncode}: stdout={stdout!r} stderr={stderr!r}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"server did not become ready: {last_error}")


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


def test_server_port_is_tracked_configuration(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")

    code, payload = invariant(repo, "settings")
    assert code == 0, payload
    assert payload["result"]["settings"]["server_port"] == "3000"

    code, payload = invariant(repo, "set", "server.port", "43123")
    assert code == 0, payload
    config = yaml.safe_load((repo / ".invariant" / "config.yml").read_text())
    assert config["server"]["port"] == 43123

    code, payload = invariant(repo, "set", "server.port", "0")
    assert code == 2
    assert payload["diagnostics"][0]["code"] == "invalid_config_value"
    assert yaml.safe_load((repo / ".invariant" / "config.yml").read_text())["server"][
        "port"
    ] == 43123

    code, payload = invariant(repo, "--server")
    assert code == 2
    assert payload["outcome"] == "failed"


def test_server_exposes_read_only_snapshot_and_changed_sse_events(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    port = _available_port()
    code, payload = invariant(repo, "set", "server.port", str(port))
    assert code == 0, payload
    fake = _fake_codex(tmp_path)
    domain = repo / ".invariant" / "records" / "domain" / "observer.yml"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "version: 1\n"
        "id: observer\n"
        "responsibility: Presents local lifecycle and evidence state.\n"
        "authority: user:task:server-test#decision\n"
    )
    git(repo, "add", ".invariant/config.yml", ".invariant/records/domain/observer.yml")
    git(repo, "commit", "-qm", "configure observer")

    code, payload = invariant(
        repo,
        "task",
        "begin",
        "landed-change",
        "--goal",
        "Create observable completed evidence.",
        "--boundary",
        "no-record",
    )
    assert code == 0, payload
    landed_worktree = Path(payload["result"]["task"]["work"]["worktree"])
    implement(landed_worktree, "src/landed.txt", "landed\n")
    code, payload = invariant(repo, "task", "finish", "landed-change")
    assert code == 0, payload

    code, payload = invariant(
        repo,
        "task",
        "begin",
        "observed-change",
        "--goal",
        "Observe this active change.",
        "--boundary",
        "no-record",
    )
    assert code == 0, payload

    process = subprocess.Popen(
        [str(CLI), "start", "--server", "--using", "codex"],
        cwd=repo,
        env={
            **os.environ,
            "INVARIANT_CODEX": str(fake),
            "INVARIANT_HOME": str(tmp_path / "invariant-home"),
            "PYTHONUNBUFFERED": "1",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    stream = None
    try:
        snapshot = _wait_for_json(f"{base_url}/api/v1/snapshot", process)
        assert snapshot["version"] == 1
        assert snapshot["repository"]["name"] == "repo"
        assert snapshot["repository"]["state"] == "valid"
        assert [item["id"] for item in snapshot["tasks"]] == ["observed-change"]
        assert snapshot["governance"]["records"][0]["id"] == "observer"
        assert snapshot["history"][0]["task"] == "landed-change"
        assert snapshot["history"][0]["boundary"] == "no-record"
        assert any(item.get("task") == "landed-change" for item in snapshot["evidence"])
        assert snapshot["tasks"][0]["freshness"] == "fresh"
        assert any(
            item["command"] == "start" and item["state"] == "running"
            for item in snapshot["processes"]
        )
        assert {"plans", "leases", "governance", "evidence", "history"}.issubset(
            snapshot
        )

        with urllib.request.urlopen(f"{base_url}/", timeout=2) as response:
            page = response.read().decode("utf-8")
            assert response.headers["Content-Security-Policy"]
            assert "Repository observer · read only" in page
            assert "No chat · no write endpoints" in page

        request = urllib.request.Request(f"{base_url}/api/v1/snapshot", method="POST")
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 405
            assert exc.headers["Allow"] == "GET, HEAD"
        else:
            raise AssertionError("server accepted a write method")

        stream = urllib.request.urlopen(f"{base_url}/api/v1/events", timeout=5)
        first = _next_snapshot(stream)
        assert first["revision"] == snapshot["revision"]

        code, payload = invariant(
            repo,
            "task",
            "begin",
            "second-change",
            "--goal",
            "Emit a changed snapshot.",
            "--boundary",
            "no-record",
        )
        assert code == 0, payload
        second = _next_snapshot(stream)
        assert second["revision"] != first["revision"]
        assert {item["id"] for item in second["tasks"]} == {
            "observed-change",
            "second-change",
        }

        config_path = repo / ".invariant" / "config.yml"
        valid_config = config_path.read_text()
        config_path.write_text(valid_config.replace(f"port: {port}", "port: invalid"))
        invalid = _next_snapshot(stream)
        assert invalid["repository"]["state"] == "invalid"
        assert "server.port" in invalid["diagnostics"][0]
        config_path.write_text(valid_config)
        recovered = _next_snapshot(stream)
        assert recovered["repository"]["state"] == "valid"
    finally:
        if stream is not None:
            stream.close()
        if process.poll() is None:
            stdout, stderr = process.communicate(input=":exit\n", timeout=10)
        else:
            stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert f"http://127.0.0.1:{port}" in stdout
        assert "SESSION: ended" in stdout
        assert "Fatal Python error" not in stderr

    try:
        urllib.request.urlopen(f"{base_url}/healthz", timeout=1)
    except urllib.error.URLError:
        pass
    else:
        raise AssertionError("server outlived its owning console session")

    process_files = list(
        (repo / ".invariant" / "runtime" / "processes").glob("*.yml")
    )
    assert process_files == []
