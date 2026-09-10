"""Observable terminal hierarchy for public commands and conversations."""

from __future__ import annotations

import errno
import os
import pty
import re
import select
import subprocess
import time
from pathlib import Path

from lifecycle_support import CLI, git, repository


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WORDMARK_TOP = "█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀"


def _fake_codex(path: Path) -> Path:
    executable = path / "codex"
    executable.write_text(
        r'''#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli presentation-test'
  exit 0
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  echo 'Logged in using test account'
  exit 0
fi
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output=$1
  fi
  shift
done
[ -n "$output" ] || exit 3
request=$(cat)
case "$request" in
  *"User message:"*"First"*) message='First answer.' ;;
  *"User message:"*"Second"*) message='Second answer.' ;;
  *) message='Repository answer.' ;;
esac
printf '{"message":"%s"}\n' "$message" >"$output"
printf '%s\n' '{"type":"thread.started","thread_id":"presentation-session"}'
printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}'
''',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _tty(
    repo: Path,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
    input_steps: list[tuple[str, str]] | None = None,
) -> tuple[int, str]:
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [str(CLI), *arguments],
        cwd=repo,
        env={
            **os.environ,
            "NO_COLOR": "1",
            "INVARIANT_NO_ANIMATION": "1",
            "TERM": "xterm-256color",
            **(environment or {}),
        },
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    chunks: list[bytes] = []
    pending = list(input_steps or [])
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
            current = b"".join(chunks).decode("utf-8", errors="replace")
            if pending and pending[0][0] in current:
                _, value = pending.pop(0)
                os.write(master, value.encode())
            if process.poll() is not None:
                while True:
                    ready, _, _ = select.select([master], [], [], 0)
                    if not ready:
                        break
                    try:
                        chunks.append(os.read(master, 4096))
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        break
                break
        else:
            process.kill()
            raise AssertionError(f"terminal command did not finish:\n{current}")
    finally:
        os.close(master)
    output = b"".join(chunks).decode("utf-8", errors="replace")
    output = _ANSI.sub("", output).replace("\r\n", "\n").replace("\r", "")
    return process.wait(timeout=2), output


def test_start_brands_once_and_separates_complete_turns(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    code, output = _tty(
        repo,
        ["start", "--using", "codex"],
        environment={
            "INVARIANT_CODEX": str(fake),
            "INVARIANT_HOME": str(tmp_path / "invariant-home"),
        },
        input_steps=[
            ("conversation", "First\n"),
            ("First answer.", "Second\n"),
            ("Second answer.", ":exit\n"),
        ],
    )

    assert code == 0, output
    assert output.startswith(f"\n{_WORDMARK_TOP}")
    assert output.count(_WORDMARK_TOP) == 1
    assert "╭" not in output
    dividers = list(re.finditer(r"(?m)^  ─{40,}$", output))
    assert len(dividers) == 2, output
    assert output.index("First answer.") < dividers[0].start() < output.index("Second")
    assert output.index("Second answer.") < dividers[1].start()
    assert "(codex) ›\n  First answer." in output
    assert not re.search(r"\(codex\) › \d", output)
    assert "Sessions  1" not in output
    assert output.rstrip().endswith("Session ended")


def test_status_keeps_repository_information_boxed(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    code, output = _tty(repo, ["status"])

    assert code == 0, output
    assert output.count(_WORDMARK_TOP) == 0
    assert "Repository" in output
    assert "Status" in output
    assert output.count("╭") == output.count("╰") == 1
    assert output.index("╭") < output.index("Status") < output.index("╰")


def test_init_is_the_only_branded_result_command(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "app.txt").write_text("seed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    fake = _fake_codex(tmp_path)

    code, output = _tty(
        repo,
        ["init", "--defaults", "--agent", "codex"],
        environment={
            "INVARIANT_CODEX": str(fake),
            "INVARIANT_HOME": str(tmp_path / "invariant-home"),
        },
        input_steps=[("○ No", "j\r")],
    )

    assert code == 0, output
    assert output.count(_WORDMARK_TOP) == 1
    assert "Repository ready" in output


def test_session_panel_leaves_space_before_the_next_prompt(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    code, output = _tty(
        repo,
        ["start", "--using", "codex"],
        environment={
            "INVARIANT_CODEX": str(fake),
            "INVARIANT_HOME": str(tmp_path / "invariant-home"),
        },
        input_steps=[
            ("conversation", ":status\n"),
            ('invariant change "Describe the change"', "\x04"),
        ],
    )

    assert code == 0, output
    assert re.search(
        r'invariant change "Describe the change"\n\n\(ask\) ›', output
    ), output
