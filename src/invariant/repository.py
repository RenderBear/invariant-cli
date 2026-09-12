"""One repository identity bound at the transport edge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from invariant.errors import InvariantError
from invariant.mechanics import config, git
from invariant.protocol import digest


@dataclass(frozen=True)
class Repository:
    root: Path
    common_dir: Path
    primary_worktree: Path
    identity: str

    @classmethod
    def bind(cls, path: Path | str = ".") -> "Repository":
        root = git.root(path)
        primary = git.primary_worktree(root).resolve()
        common = git.common_dir(root)
        initial = git.run(
            ["rev-list", "--max-parents=0", "--reverse", "HEAD"],
            cwd=root,
            check=False,
        )
        if initial.returncode == 0 and initial.stdout:
            identity = initial.stdout.splitlines()[0]
        else:
            nonce_path = common / "invariant-bootstrap"
            if not nonce_path.is_file():
                raise InvariantError(
                    "Invariant: unborn repository has no bootstrap identity; run invariant init",
                    code="not_initialized",
                )
            identity = digest({"bootstrap": nonce_path.read_text(encoding="utf-8").strip()})
        return cls(root.resolve(), common, primary, identity)

    @property
    def policy(self) -> config.Config:
        return config.resolve(self.primary_worktree)

    def policy_at(self, ref: str, integration_branch: str) -> config.Config:
        """Load tracked policy from one exact accepted Git ground."""

        return config.resolve_at(self.primary_worktree, ref, integration_branch)

    def ref(self, change_id: str) -> str:
        return f"refs/invariant/changes/{change_id}"
