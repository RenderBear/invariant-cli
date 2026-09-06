from __future__ import annotations

from typing import Any


AUDIT_PROPOSED = [
    "architecture",
    "constraint",
    "contract",
    "discovery",
    "domain",
    "none",
    "observation",
]
AUDIT_DISPOSITIONS = [
    "adoptable",
    "discovery-only",
    "needs-authority",
    "needs-verifier",
    "no-action",
    "observation-only",
]


def audit_input_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant audit findings input",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "findings"],
        "properties": {
            "version": {"const": 1},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "summary", "evidence", "proposed", "disposition"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$",
                        },
                        "summary": {"type": "string", "minLength": 1},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "description": "repo:<path>, commit:<ref>, interface:<name>, task:<id>, or url:https://...",
                            },
                        },
                        "proposed": {"enum": AUDIT_PROPOSED},
                        "disposition": {"enum": AUDIT_DISPOSITIONS},
                        "authority": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Optional inspectable user:, design:, or architecture: locator.",
                        },
                    },
                },
            },
        },
    }


def audit_input_example() -> dict[str, Any]:
    return {
        "version": 1,
        "findings": [
            {
                "id": "job-recovery-boundary",
                "summary": "Restart recovery behavior is relied on but not recorded.",
                "evidence": ["repo:src/jobs.py", "repo:tests/test_jobs.py"],
                "proposed": "architecture",
                "disposition": "adoptable",
            }
        ],
    }


def assessment_schema() -> dict[str, Any]:
    string_list = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "uniqueItems": True,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant task assessment",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "version",
            "goal_digest",
            "paths",
            "interfaces",
            "domains",
            "boundary",
            "governance",
            "architecture_reviews",
            "checks",
        ],
        "properties": {
            "version": {"const": 1},
            "goal_digest": {"type": "string", "minLength": 1},
            "paths": {
                **string_list,
                "minItems": 1,
                "description": "Repository-relative candidate paths; assessment prepare fills these exactly.",
            },
            "interfaces": {
                **string_list,
                "description": "Interface names selected for semantic reach.",
            },
            "domains": {
                **string_list,
                "description": "Registered domain IDs, including domains established by this candidate.",
            },
            "boundary": {
                "type": "object",
                "additionalProperties": False,
                "required": ["disposition"],
                "properties": {
                    "disposition": {
                        "type": "string",
                        "description": "no-record, recorded, or audit:<id>",
                        "pattern": "^(no-record|recorded|audit:[A-Za-z0-9][A-Za-z0-9._-]*)$",
                    }
                },
            },
            "governance": {
                **string_list,
                "description": "Candidate records: semantic:<id>, domain:<id>, contract:<id>, constraint:<id>, or architecture:<path>#<anchor>.",
            },
            "architecture_reviews": {
                **string_list,
                "description": "Registered architecture:<path>#<anchor> locators reviewed against the prospective tree.",
            },
            "checks": {
                **string_list,
                "description": "Additional command:<path>, test:<path>, schema:<path>, or runner:<name>#<target> verifiers.",
            },
            "allow_open": {
                "type": "boolean",
                "description": "Explicit authority acknowledgement for open or gated reach; generated by assessment prepare.",
            },
            "prose": {"type": "string"},
        },
    }


def assessment_example() -> dict[str, Any]:
    return {
        "version": 1,
        "goal_digest": "<from task receipt>",
        "paths": ["src/jobs.py"],
        "interfaces": [],
        "domains": ["jobs"],
        "boundary": {"disposition": "no-record"},
        "governance": [],
        "architecture_reviews": ["architecture:docs/architecture.md#job-recovery"],
        "checks": [],
        "allow_open": False,
    }
