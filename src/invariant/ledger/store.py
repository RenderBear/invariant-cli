from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.harness.identity import HOST_TTY, UNAUTHENTICATED, refusal_lines
from invariant.ledger.events import Event, reduce_event, serialized
from invariant.mechanics import git
from invariant.protocol import (
    EventKind,
    canonical_json,
    digest,
    require_authority_locator,
    require_id,
)
from invariant.repository import Repository


@dataclass(frozen=True)
class Ledger:
    change_id: str
    head: str
    state: Mapping[str, Any]
    _loader: Any = None

    def operation(self, operation_id: str) -> Mapping[str, Any] | None:
        operations = self.state.get("operations", {})
        return operations.get(operation_id) if isinstance(operations, dict) else None

    def event_for(self, operation_id: str) -> Event | None:
        """Read the one event an operation id recorded, by its sequence, without replaying."""

        recorded = self.operation(operation_id)
        if not recorded or self._loader is None:
            return None
        return self._loader(int(recorded["sequence"]))


class LedgerStore:
    def __init__(
        self,
        repository: Repository,
        *,
        principal: str,
        authentication: str = UNAUTHENTICATED,
    ) -> None:
        require_authority_locator(principal, "transport principal")
        if principal.startswith("user:") and authentication != HOST_TTY:
            raise InvariantError(
                f"Invariant: user principal '{principal}' requires an authenticated host transport",
                code="unauthenticated_principal",
                lines=refusal_lines(),
            )
        self.repository = repository
        self.principal = principal
        self.authentication = authentication if principal.startswith("user:") else UNAUTHENTICATED

    def ref(self, change_id: str) -> str:
        require_id(change_id, "change id")
        return self.repository.ref(change_id)

    def head(self, change_id: str) -> str | None:
        return git.resolve(self.repository.root, self.ref(change_id))

    def load(self, change_id: str) -> Ledger:
        """Load the head snapshot; the full chain is verified by ``verify``."""

        ref = self.ref(change_id)
        head = git.resolve(self.repository.root, ref)
        if not head:
            archived = git.resolve(self.repository.root, self.repository.archive_ref(change_id))
            if archived:
                return self._load_head(change_id, archived)
            raise InvariantError(
                f"Invariant: change '{change_id}' does not exist", code="missing_change"
            )
        return self._load_head(change_id, head)

    def _load_head(self, change_id: str, head: str) -> Ledger:
        objects = git.cat_files(
            self.repository.root,
            [f"{head}:event.json", f"{head}:event.sha256", f"{head}:snapshot.json"],
        )
        event = Event.parse(self._decode_json(objects[f"{head}:event.json"], head, "event.json"))
        if objects[f"{head}:event.sha256"].decode("utf-8").strip() != event.digest:
            raise InvariantError("Invariant: corrupt ledger event checksum", code="corrupt_ledger")
        state = self._decode_json(objects[f"{head}:snapshot.json"], head, "snapshot.json")
        if (
            not isinstance(state, dict)
            or state.get("change") != change_id
            or state.get("sequence") != event.sequence
            or state.get("last_event") != event.digest
        ):
            raise InvariantError("Invariant: corrupt ledger snapshot", code="corrupt_ledger")

        def loader(sequence: int) -> Event | None:
            distance = event.sequence - sequence
            if distance < 0:
                return None
            raw = git.run(
                ["show", f"{head}~{distance}:event.json"], cwd=self.repository.root, check=False
            )
            if raw.returncode:
                return None
            return Event.parse(json.loads(raw.stdout))

        return Ledger(change_id, head, state, loader)

    def verify(self, change_id: str) -> Ledger:
        """Replay and verify the whole chain: first parents, sequences, digests, and snapshots."""

        ref = self.ref(change_id)
        head = git.resolve(self.repository.root, ref) or git.resolve(
            self.repository.root, self.repository.archive_ref(change_id)
        )
        if not head:
            raise InvariantError(
                f"Invariant: change '{change_id}' does not exist", code="missing_change"
            )
        history_rows = git.run(
            ["rev-list", "--first-parent", "--reverse", "--parents", head],
            cwd=self.repository.root,
        ).stdout.splitlines()
        history = [row.split()[0] for row in history_rows]
        objects = git.cat_files(
            self.repository.root,
            [f"{commit}:{name}" for commit in history for name in ("event.json", "event.sha256", "snapshot.json")],
        )
        state: Mapping[str, Any] | None = None
        events: list[Event] = []
        prior: str | None = None
        for index, (commit, history_row) in enumerate(zip(history, history_rows), 1):
            parents = history_row.split()[1:]
            first_parent = parents[0] if parents else None
            if first_parent != prior:
                raise InvariantError("Invariant: corrupt ledger first-parent chain", code="corrupt_ledger")
            raw_event = self._decode_json(objects[f"{commit}:event.json"], commit, "event.json")
            event = Event.parse(raw_event)
            if event.sequence != index or event.prior != prior:
                raise InvariantError("Invariant: corrupt ledger causal binding", code="corrupt_ledger")
            stored_digest = objects[f"{commit}:event.sha256"].decode("utf-8").strip()
            if stored_digest != event.digest:
                raise InvariantError("Invariant: corrupt ledger event checksum", code="corrupt_ledger")
            state = reduce_event(state, event)
            stored_snapshot = self._decode_json(objects[f"{commit}:snapshot.json"], commit, "snapshot.json")
            if canonical_json(stored_snapshot) != canonical_json(state):
                raise InvariantError("Invariant: corrupt ledger snapshot", code="corrupt_ledger")
            events.append(event)
            prior = commit
        if not isinstance(state, dict) or state.get("change") != change_id:
            raise InvariantError("Invariant: ledger change identity mismatch", code="corrupt_ledger")
        return self._load_head(change_id, head)

    def append(
        self,
        change_id: str,
        *,
        operation_id: str,
        kind: EventKind,
        actor: str,
        payload: Mapping[str, Any],
        expected_head: str | None = None,
        anchors: Iterable[str] = (),
    ) -> Ledger:
        require_id(change_id, "change id")
        current_head = self.head(change_id)
        ledger = self.load(change_id) if current_head else None
        if expected_head is not None and expected_head != current_head:
            raise Blocked(
                "Invariant: change ledger advanced; recomputation is required",
                code="concurrent_ledger_movement",
                data={"expected": expected_head, "actual": current_head},
            )
        request_digest = digest(
            {
                "kind": kind.value,
                "actor": actor,
                "principal": self.principal,
                "authentication": self.authentication,
                "payload": payload,
            }
        )
        if ledger:
            existing = ledger.operation(operation_id)
            if existing:
                if existing.get("request_digest") != request_digest:
                    raise InvariantError(
                        "Invariant: operation id was reused with different input",
                        code="corrupt_ledger",
                    )
                return ledger
        event = Event.create(
            sequence=(int(ledger.state["sequence"]) + 1 if ledger else 1),
            operation_id=operation_id,
            kind=kind,
            actor=actor,
            principal=self.principal,
            authentication=self.authentication,
            prior=current_head,
            payload=payload,
        )
        state = reduce_event(ledger.state if ledger else None, event)
        blobs = {
            "event.json": git.write_blob(self.repository.root, serialized(event.as_dict())),
            "event.sha256": git.write_blob(self.repository.root, event.digest + "\n"),
            "snapshot.json": git.write_blob(self.repository.root, serialized(state)),
        }
        tree = git.write_tree(self.repository.root, blobs)
        # The opening ledger commit is a root. Otherwise the preceding ledger
        # event is always first parent and referenced work may be extra parents.
        parent_values = ([current_head] if current_head else []) + (
            [
                value
                for value in dict.fromkeys(anchors)
                if value and value != current_head
            ]
            if current_head
            else []
        )
        for anchor in parent_values:
            if not git.resolve(self.repository.root, anchor):
                raise InvariantError(
                    f"Invariant: ledger anchor '{anchor}' does not resolve", code="missing_object"
                )
        commit = git.commit_tree(
            self.repository.root,
            tree,
            f"Invariant ledger: {change_id} {event.kind.value}\n\nInvariant-Event: {event.digest}\n",
            parents=parent_values,
        )
        if not git.update_ref(self.repository.root, self.ref(change_id), commit, current_head):
            raise Blocked(
                "Invariant: concurrent ledger movement",
                code="concurrent_ledger_movement",
                data={"expected": current_head, "actual": self.head(change_id)},
            )
        return self.load(change_id)

    def archive(self, change_id: str) -> str:
        """Move a completed change's ledger ref to the archive namespace; nothing is deleted."""

        ref = self.ref(change_id)
        head = git.resolve(self.repository.root, ref)
        if not head:
            raise InvariantError(
                f"Invariant: change '{change_id}' is not an active ledger", code="missing_change"
            )
        archive_ref = self.repository.archive_ref(change_id)
        if not git.update_ref(self.repository.root, archive_ref, head, None):
            raise Blocked("Invariant: archive ref already exists", code="concurrent_ref_movement")
        if not git.delete_ref(self.repository.root, ref, head):
            raise Blocked("Invariant: ledger moved during archival", code="concurrent_ledger_movement")
        return archive_ref

    def _json_file(self, commit: str, name: str) -> Any:
        result = git.run(["show", f"{commit}:{name}"], cwd=self.repository.root, check=False)
        if result.returncode:
            raise InvariantError(
                f"Invariant: ledger commit '{commit}' lacks {name}", code="corrupt_ledger"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InvariantError(
                f"Invariant: ledger commit '{commit}' has invalid {name}", code="corrupt_ledger"
            ) from exc

    @staticmethod
    def _decode_json(content: bytes, commit: str, name: str) -> Any:
        try:
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvariantError(
                f"Invariant: ledger commit '{commit}' has invalid {name}", code="corrupt_ledger"
            ) from exc
