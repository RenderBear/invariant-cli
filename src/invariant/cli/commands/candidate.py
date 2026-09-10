from __future__ import annotations

import argparse

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import config, git, governance, landing
from invariant.semantics.models import Assessment


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("candidate", help="Verify or explicitly land a candidate branch")
    commands = parser.add_subparsers(dest="candidate_command", required=True)
    for name, handler in (("verify", _verify), ("land", _land)):
        command = commands.add_parser(name)
        command.add_argument("branch")
        command.add_argument("--assessment", required=True)
        command.add_argument("--target")
        command.add_argument("--unit", default="candidate")
        command.add_argument("--subject", default="Invariant candidate")
        command.add_argument("--check", action="append", default=[])
        command.set_defaults(_handler=handler, _command=f"candidate.{name}")


def _request(args: argparse.Namespace) -> landing.LandRequest:
    repo = git.root()
    assessment = Assessment.load(args.assessment)
    target = args.target or config.resolve(repo).integration_branch
    old = git.resolve(repo, f"refs/heads/{target}")
    branch = git.resolve(repo, f"refs/heads/{args.branch}")
    if not old or not branch:
        raise InvariantError("Invariant: candidate and target must resolve to local commits")
    changed = git.changed_paths(repo, old, branch)
    for path in changed:
        if not any(path == claim or path.startswith(claim + "/") for claim in assessment.paths):
            raise Blocked(f"Invariant: candidate path '{path}' is absent from the assessment")
    context = governance.context_result(
        repo,
        paths=changed,
        base=old,
        domains_selected=assessment.domains,
        interfaces=assessment.interfaces,
    )
    scopes = context.topology or ("area.root",)
    return landing.LandRequest(
        mode="merge",
        merge_branch=args.branch,
        subject=args.subject,
        units=(args.unit,),
        scopes=scopes,
        boundary=assessment.boundary.disposition,
        domains=tuple(assessment.domains),
        interfaces=tuple(assessment.interfaces),
        governance_refs=tuple(assessment.governance),
        reviewed=tuple(assessment.architecture_reviews),
        checks=tuple(sorted(set([*assessment.checks, *args.check]))),
        target=target,
        allow_open=assessment.allow_open,
    )


def _verify(args: argparse.Namespace) -> list[str]:
    return landing.verify_and_land(git.root(), _request(args), update_ref=False)


def _land(args: argparse.Namespace) -> list[str]:
    return landing.verify_and_land(git.root(), _request(args), update_ref=True)
