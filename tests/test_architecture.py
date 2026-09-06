from __future__ import annotations

import ast
from pathlib import Path

import yaml

from invariant import adapters
from invariant.adapters.task_contract import TaskContract, TaskContractReview
from invariant.semantics import guidance
from invariant.semantics.discovery import Discovery, validate_shape
from invariant.semantics.models import Assessment


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


def test_protocol_uses_the_new_namespace() -> None:
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Intent-" not in text, path
        assert "intent/work/" not in text, path
        assert "GIT_INTENT_" not in text, path


def test_task_contract_keeps_prose_and_stable_ids(tmp_path: Path) -> None:
    path = tmp_path / "contract.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "adapter": "task_contract",
                "source_goal_digest": "goal-id",
                "requirements": {
                    "goal": "Restore active jobs after reopening.",
                    "outcomes": [{"id": "O1", "prose": "Active jobs remain visible."}],
                    "acceptance": [{"id": "A1", "prose": "Each job appears once."}],
                    "constraints": [{"id": "C1", "prose": "Chat remains session scoped."}],
                },
                "verification": {
                    "level": "targeted",
                    "rationale": "A bounded behavior change has focused existing tests.",
                },
            }
        ),
        encoding="utf-8",
    )
    contract = TaskContract.load(path)
    assert contract.goal == "Restore active jobs after reopening."
    assert contract.nodes["outcomes"] == ["O1"]
    assert contract.required == ["A1", "C1"]
    assert contract.nodes["constraints"] == ["C1"]
    assert contract.verification_level == "targeted"
    assert "Active jobs remain visible." in path.read_text(encoding="utf-8")


def test_task_contract_review_is_separate_exact_tree_adapter_input(tmp_path: Path) -> None:
    path = tmp_path / "review.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "adapter": "task_contract",
                "source_goal_digest": "abc",
                "candidate_tree": "tree-id",
                "results": [
                    {
                        "satisfies": "A1",
                        "disposition": "satisfied",
                        "prose": "The candidate restores each job once.",
                        "evidence": ["test:tests/test_jobs.py"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    review = TaskContractReview.load(path)
    assert review.candidate_tree == "tree-id"
    assert review.results[0].reference == "A1"
    assert review.results[0].disposition == "satisfied"


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
    assert "# Brief" in text
    assert "# Durable semantic reasoning" in text
    assert "# Repository archaeology" in text
    assert "# Progressive discovery" in text
    assert "# Coordinate" in text
    assert "# Land" in text
    assert "# Human ergonomics" in text
    assert "# Agent protocol reference" in text
    assert "Requested meaning" in text
    assert "Trace behavior end to end" in text


def test_task_contract_is_a_bundled_adapter_not_semantics() -> None:
    adapter = adapters.task_contract_examples()
    assert adapter["contract"]["adapter"] == "task_contract"
    assert adapter["review"]["adapter"] == "task_contract"
    assert not (PACKAGE / "semantics" / "guidance" / "task-acceptance.md").exists()
    assert not (PACKAGE / "semantics" / "guidance" / "outcome-review.md").exists()
    for path in (PACKAGE / "adapters").rglob("*.py"):
        imports = imported_modules(path)
        assert not any(name.startswith("invariant.lifecycle") for name in imports), path


def test_task_contract_example_allows_inspection_without_a_persisted_test(tmp_path: Path) -> None:
    examples = adapters.task_contract_examples()
    contract_path = tmp_path / "contract.yml"
    review_path = tmp_path / "review.yml"
    contract_path.write_text(yaml.safe_dump(examples["contract"]), encoding="utf-8")
    review_path.write_text(yaml.safe_dump(examples["review"]), encoding="utf-8")
    contract = TaskContract.load(contract_path)
    review = TaskContractReview.load(review_path)
    assert contract.verification_level == "inspection"
    assert review.results[0].evidence == ["inspection:src/components/SaveButton.tsx"]


def test_installed_agent_workflow_matches_portable_reference() -> None:
    example = (REPOSITORY / "AGENTS.example.md").read_text(encoding="utf-8")
    fenced = example.split("````markdown\n", 1)[1].rsplit("\n````", 1)[0].strip()
    assert fenced == guidance.agent_workflow()
    assert "# Human ergonomics" not in guidance.agent_workflow()
    assert "### Start and implement" in guidance.agent_workflow()
    assert len(guidance.agent_workflow().splitlines()) < 60
