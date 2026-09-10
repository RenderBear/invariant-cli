from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from invariant.cli.output import CommandResult
from invariant.errors import Blocked
from invariant.mechanics import audit, config, git
from invariant.semantics import schemas


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("evidence", help="Audit and record progressive discoveries")
    commands = parser.add_subparsers(dest="evidence_command", required=True)
    audit_parser = commands.add_parser("audit", help="Frame and persist causally grounded audits")
    audits = audit_parser.add_subparsers(dest="audit_command", required=True)
    scope = audits.add_parser("scope", help="Frame a read-only audit for explicit repository paths")
    scope.add_argument("--path", action="append", required=True, help="repository-relative path")
    scope.set_defaults(_handler=_scope, _command="evidence.audit.scope")
    full = audits.add_parser("full", help="Frame a repository-wide governance audit")
    full.set_defaults(_handler=_full, _command="evidence.audit.full")
    save = audits.add_parser("save", help="Stamp, validate, and save completed audit findings")
    save.add_argument("audit_id")
    save.add_argument("--mode", choices=["scope", "full"], required=True)
    save.add_argument(
        "--input",
        type=Path,
        required=True,
        help="version-1 YAML containing only a findings list; Invariant stamps causal fields",
    )
    save.add_argument(
        "--path", action="append", default=[], help="required scope path in scope mode"
    )
    save.add_argument(
        "--domain", action="append", default=[], help="existing domain relevant to the audit"
    )
    save.set_defaults(_handler=_save, _command="evidence.audit.save")
    schema = audits.add_parser("schema", help="Print the complete audit findings input schema")
    schema.set_defaults(_handler=_schema, _command="evidence.audit.schema")
    example = audits.add_parser("example", help="Print a valid audit findings input example")
    example.set_defaults(_handler=_example, _command="evidence.audit.example")
    fresh = commands.add_parser("fresh")
    fresh.add_argument("locator")
    fresh.add_argument("--at", default="HEAD")
    fresh.set_defaults(_handler=_fresh, _command="evidence.fresh")
    discovery = commands.add_parser("discovery")
    discoveries = discovery.add_subparsers(dest="discovery_command", required=True)
    capture = discoveries.add_parser("capture")
    capture.add_argument("discovery_id")
    capture.add_argument("--observation", required=True)
    capture.add_argument("--evidence", action="append", default=[])
    capture.add_argument("--searched", action="append", default=[])
    capture.add_argument("--basis-prose", default="")
    capture.add_argument("--domain", action="append", default=[])
    capture.add_argument("--path", action="append", default=[])
    capture.add_argument("--related", action="append", default=[])
    capture_action = capture.add_mutually_exclusive_group()
    capture_action.add_argument("--dry-run", action="store_true")
    capture_action.add_argument("--apply", action="store_true")
    capture.set_defaults(_handler=_capture, _command="evidence.discovery.capture")
    resolve = discoveries.add_parser("resolve")
    resolve.add_argument("discovery_id")
    resolve.add_argument("--prose", default="")
    resolve.add_argument("--output", action="append", default=[])
    resolve_action = resolve.add_mutually_exclusive_group()
    resolve_action.add_argument("--dry-run", action="store_true")
    resolve_action.add_argument("--apply", action="store_true")
    resolve.set_defaults(_handler=_resolve, _command="evidence.discovery.resolve")


def _scope(args: argparse.Namespace) -> list[str]:
    return audit.frame(git.root(), "scope", args.path)


def _full(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    return audit.full(repo, _authority_mode(repo))


def _authority_mode(repo: Path) -> str:
    proposed = config.resolve(repo)
    if proposed.authority != "agent":
        return "human"
    ground = git.resolve(repo, f"refs/heads/{proposed.integration_branch}")
    if not ground:
        return "human"
    accepted = config.resolve_at(repo, ground, proposed.integration_branch)
    return "agent" if accepted.authority == "agent" else "human"


def _save(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    return audit.save(
        repo,
        args.audit_id,
        mode=args.mode,
        source=args.input,
        paths=args.path,
        domains=args.domain,
        authority=_authority_mode(repo),
    )


def _yaml_lines(value: object) -> list[str]:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip().splitlines()


def _schema(_: argparse.Namespace) -> CommandResult:
    value = schemas.audit_input_schema()
    return CommandResult(_yaml_lines(value), {"schema": value})


def _example(_: argparse.Namespace) -> CommandResult:
    value = schemas.audit_input_example()
    return CommandResult(_yaml_lines(value), {"example": value})


def _fresh(args: argparse.Namespace) -> list[str]:
    return audit.fresh(git.root(), args.locator, args.at)


def _capture(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    preview = args.dry_run or (_authority_mode(repo) == "human" and not args.apply)
    lines = audit.capture_discovery(
        repo,
        args.discovery_id,
        observation=args.observation,
        evidence=args.evidence,
        searched=args.searched,
        basis_prose=args.basis_prose,
        domains=args.domain,
        paths=args.path,
        related=args.related,
        dry_run=preview,
    )
    if preview and not args.dry_run:
        observation = " ".join(args.observation.split())
        raise Blocked(
            "Invariant: human authority requires approval before recording a discovery",
            code="authority_required",
            lines=[
                f"PROPOSAL: record discovery {args.discovery_id} — {observation}",
                *lines,
                "NEXT: after human approval, the harness must rerun this command with --apply",
            ],
        )
    return lines


def _resolve(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    preview = args.dry_run or (_authority_mode(repo) == "human" and not args.apply)
    lines = audit.resolve_discovery(
        repo, args.discovery_id, prose=args.prose, outputs=args.output, dry_run=preview
    )
    if preview and not args.dry_run:
        raise Blocked(
            "Invariant: human authority requires approval before resolving a discovery",
            code="authority_required",
            lines=[
                f"PROPOSAL: resolve discovery {args.discovery_id}",
                *lines,
                "NEXT: after human approval, the harness must rerun this command with --apply",
            ],
        )
    return lines
