from __future__ import annotations

import ast
from pathlib import Path

import yaml

from invariant import adapters
from invariant.adapters.base import CANDIDATE_EVIDENCED, HOOK_PHASES, TASK_CREATED
from invariant.adapters.intent_brief.models import IntentBrief, IntentReview
from invariant.semantics import guidance
from invariant.semantics.adoption import AdoptionManifest
from invariant.semantics.discovery import Discovery, validate_shape
from invariant.semantics.models import Assessment
from invariant.semantics.records import parse_document
from invariant.mechanics import landing


PACKAGE = Path(__file__).parents[1] / "src" / "invariant"
REPOSITORY = Path(__file__).parents[1]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_semantics_does_not_depend_on_mechanics_or_lifecycle() -> None:
    for path in (PACKAGE / "semantics").glob("*.py"):
        imports = imported_modules(path)
        assert not any(name.startswith("invariant.mechanics") for name in imports), path
        assert not any(name.startswith("invariant.lifecycle") for name in imports), path


def test_mechanics_does_not_depend_on_lifecycle_or_skill_source() -> None:
    for path in (PACKAGE / "mechanics").glob("*.py"):
        imports = imported_modules(path)
        assert not any(name.startswith("invariant.lifecycle") for name in imports), path
        assert "skills/" not in path.read_text(encoding="utf-8")


def test_landing_accepts_architecture_registered_by_an_active_semantic_record(
    tmp_path: Path,
) -> None:
    (tmp_path / ".invariant").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(
        "# Architecture\n\n## Application boundary\n\nThe application owns recovery.\n",
        encoding="utf-8",
    )
    (tmp_path / ".invariant" / "SEMANTICS.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "records": [
                    {
                        "id": "application-boundary",
                        "document": "architecture:docs/architecture.md#application-boundary",
                        "authority": "design:repo:docs/architecture.md#application-boundary",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert landing._governance_exists(
        tmp_path, "architecture:docs/architecture.md#application-boundary"
    )


def test_protocol_uses_the_new_namespace() -> None:
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Intent-" not in text, path
        assert "intent/work/" not in text, path
        assert "GIT_INTENT_" not in text, path


def test_intent_brief_keeps_one_prose_body_and_material_questions(tmp_path: Path) -> None:
    path = tmp_path / "brief.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "adapter": "intent_brief",
                "source_goal_digest": "goal-id",
                "brief": "Restore active jobs once after reopening; keep chat session scoped.",
                "questions": [
                    {"id": "retention", "prompt": "How long should jobs remain?", "answer": ""}
                ],
            }
        ),
        encoding="utf-8",
    )
    brief = IntentBrief.load(path)
    assert "Restore active jobs" in brief.brief
    assert [question.identifier for question in brief.unanswered] == ["retention"]


def test_intent_review_separates_candidate_defects_from_retained_discoveries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "adapter": "intent_brief",
                "source_goal_digest": "abc",
                "brief_digest": "brief-id",
                "candidate_tree": "tree-id",
                "verdict": "accepted",
                "summary": "The exact candidate restores each job once.",
                "candidate_defects": [],
                "retained_discoveries": ["discovery:legacy-recovery-gap"],
            }
        ),
        encoding="utf-8",
    )
    review = IntentReview.load(path)
    assert review.candidate_tree == "tree-id"
    assert review.verdict == "accepted"
    assert review.candidate_defects == []
    assert review.retained_discoveries == ["discovery:legacy-recovery-gap"]


def test_adoption_draft_projects_audit_records_and_flags_only_ambiguity() -> None:
    manifest = AdoptionManifest.from_audit(
        "audit-1",
        [
            {
                "id": "known-domain",
                "records": [
                    {
                        "kind": "domain",
                        "value": {
                            "id": "jobs",
                            "responsibility": "Owns job recovery.",
                            "authority": "user:task:review#decision",
                        },
                    }
                ],
            },
            {"id": "ambiguous-contract"},
        ],
        ["known-domain", "ambiguous-contract"],
    )
    assert manifest.mappings[0].records[0].reference == "domain:jobs"
    assert manifest.mappings[1].unresolved


def test_discovery_can_resolve_without_a_contract() -> None:
    raw = {
        "version": 1,
        "id": "missing-adr",
        "observation": "The recovery decision is undocumented.",
        "basis": {
            "ground": "abc",
            "tree": "def",
            "searched": ["docs", "src/jobs"],
            "prose": "The search found behavior but no rationale.",
        },
        "relevance": {"paths": ["src/jobs"], "related": ["task:document-recovery"]},
        "disposition": {
            "state": "resolved",
            "prose": "Documentation work is tracked separately.",
            "outputs": ["task:document-recovery"],
        },
    }
    discovery = Discovery.parse(raw)
    assert discovery.disposition.outputs == ["task:document-recovery"]
    assert validate_shape(Path(".invariant/discoveries/missing-adr.yml"), raw) == []


def test_stage_guidance_remains_free_form_and_composable() -> None:
    text = guidance.for_stage("implementing")
    assert "# Land" in text
    assert "# Brief" not in text
    assert "# Human ergonomics" not in text
    assert "# Repository archaeology" not in text
    full = guidance.for_stage("implementing", full=True)
    assert "# Durable semantic reasoning" in full
    assert "# Repository archaeology" in full
    assert "# Agent protocol reference" in full


def test_intent_brief_is_a_bundled_adapter_not_semantics() -> None:
    adapter = adapters.examples()
    assert adapter["brief"]["adapter"] == "intent_brief"
    assert adapter["review"]["adapter"] == "intent_brief"
    assert set(HOOK_PHASES) == {TASK_CREATED, CANDIDATE_EVIDENCED}
    for path in (PACKAGE / "adapters").rglob("*.py"):
        imports = imported_modules(path)
        assert not any(name.startswith("invariant.lifecycle") for name in imports), path


def test_intent_brief_examples_are_valid_without_a_requirement_matrix(tmp_path: Path) -> None:
    examples = adapters.examples()
    contract_path = tmp_path / "brief.yml"
    review_path = tmp_path / "review.yml"
    contract_path.write_text(yaml.safe_dump(examples["brief"]), encoding="utf-8")
    review_path.write_text(yaml.safe_dump(examples["review"]), encoding="utf-8")
    brief = IntentBrief.load(contract_path)
    review = IntentReview.load(review_path)
    assert brief.questions == []
    assert review.verdict == "accepted"


def test_semantic_record_is_a_small_open_envelope() -> None:
    records = parse_document(
        {
            "version": 1,
            "records": [
                {
                    "id": "job-recovery",
                    "document": "architecture:docs/architecture.md#job-recovery",
                    "authority": "user:task:recovery#turn-2",
                    "applies_to": ["repo:src/jobs", "interface:jobs-v1"],
                    "revisit_on": ["repo:src/storage"],
                    "relations": {"challenges": ["semantic:session-only-jobs"]},
                    "facets": {"confidence": "provisional", "vocabulary": ["active job"]},
                }
            ],
        }
    )
    assert records[0].identifier == "job-recovery"
    assert records[0].relations["challenges"] == ["semantic:session-only-jobs"]
    assert records[0].facets["confidence"] == "provisional"


def test_installed_agent_workflow_matches_portable_reference() -> None:
    example = (REPOSITORY / "AGENTS.example.md").read_text(encoding="utf-8")
    fenced = example.split("````markdown\n", 1)[1].rsplit("\n````", 1)[0].strip()
    assert fenced == guidance.agent_workflow()
    assert "# Human ergonomics" not in guidance.agent_workflow()
    assert "### Start and implement" in guidance.agent_workflow()
    assert len(guidance.agent_workflow().splitlines()) < 60
