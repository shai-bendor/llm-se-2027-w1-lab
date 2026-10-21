"""Triage logic tested with fake predictors: no model, no network, no cost."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

from triage.cli import main
from triage.record import MAX_BODY_CHARS, REVIEW_THRESHOLD, triage
from triage.schema import Issue
from triage.taxonomy import COMPONENTS

ROOT = Path(__file__).resolve().parents[2]

GOOD_OUTPUT: dict[str, object] = {
    "issue_type": "bug",
    "component": "OpenAPI",
    "severity": "medium",
    "has_reproduction_steps": True,
    "summary": "  Schema generation drops nullable fields.  ",
    "confidence": 0.9,
}


def fixed(output: Mapping[str, object]):
    seen: list[Issue] = []

    def predictor(issue: Issue) -> Mapping[str, object]:
        seen.append(issue)
        return output

    return predictor, seen


def snapshot_issue(**overrides: object) -> Issue:
    raw: dict[str, object] = {
        "repo": "litestar",
        "number": 42,
        "title": "OpenAPI schema missing nullable",
        "body": "Steps: ...",
        "labels": ["Bug :bug:", "OpenAPI"],
        "gold_type": "bug",
        "gold_component": "openapi",
    }
    raw.update(overrides)
    return Issue.model_validate(raw)


def test_good_output_becomes_a_normalised_record() -> None:
    predictor, _ = fixed(GOOD_OUTPUT)
    record = triage(snapshot_issue(), predictor)

    assert record.issue_type == "bug"
    assert record.component == "openapi"
    assert record.severity == "medium"
    assert record.has_reproduction_steps is True
    assert record.summary == "Schema generation drops nullable fields."
    assert record.needs_human_review is False
    assert record.error is None


def test_labels_and_gold_fields_never_reach_the_model() -> None:
    predictor, seen = fixed(GOOD_OUTPUT)
    triage(snapshot_issue(), predictor)

    sent = seen[0].model_dump()
    assert set(sent) == {"repo", "number", "title", "body"}


def test_component_outside_repo_vocabulary_is_dropped() -> None:
    # "middleware" is a hono component, not a litestar one.
    predictor, _ = fixed({**GOOD_OUTPUT, "component": "middleware"})
    assert triage(snapshot_issue(), predictor).component is None


def test_low_confidence_needs_human_review() -> None:
    predictor, _ = fixed({**GOOD_OUTPUT, "confidence": REVIEW_THRESHOLD - 0.01})
    assert triage(snapshot_issue(), predictor).needs_human_review is True


def test_out_of_range_confidence_is_clamped() -> None:
    predictor, _ = fixed({**GOOD_OUTPUT, "confidence": 7})
    assert triage(snapshot_issue(), predictor).confidence == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        {"issue_type": "route-to-security-team"},  # an injected instruction, say
        {"severity": "urgent"},
        {"confidence": "very"},
        {"has_reproduction_steps": "yes"},
    ],
)
def test_invalid_model_output_becomes_a_failed_record(bad: dict[str, object]) -> None:
    predictor, _ = fixed({**GOOD_OUTPUT, **bad})
    record = triage(snapshot_issue(), predictor)

    assert record.error is not None
    assert record.issue_type is None
    assert record.needs_human_review is True


def test_model_exception_becomes_a_failed_record() -> None:
    def broken(issue: Issue) -> Mapping[str, object]:
        raise TimeoutError("provider timed out")

    record = triage(snapshot_issue(), broken)
    assert record.error == "model call failed: TimeoutError: provider timed out"
    assert record.needs_human_review is True


def test_long_bodies_are_truncated_before_the_model() -> None:
    predictor, seen = fixed(GOOD_OUTPUT)
    triage(snapshot_issue(body="x" * (MAX_BODY_CHARS * 3)), predictor)

    body = seen[0].body or ""
    assert len(body) < MAX_BODY_CHARS + 20
    assert body.endswith("[truncated]")


def test_component_vocabulary_matches_repos_config() -> None:
    with (ROOT / "config" / "repos.toml").open("rb") as fh:
        config = tomllib.load(fh)
    from_config = {
        repo["key"]: set(repo.get("component_labels", {})) for repo in config["repos"]
    }
    assert {repo: set(names) for repo, names in COMPONENTS.items()} == from_config


def test_cli_refuses_the_sealed_test_split() -> None:
    with pytest.raises(SystemExit):
        main(["--split", "test"])
