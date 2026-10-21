"""Turn an issue plus untrusted model output into a validated TriageRecord."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from triage.schema import ISSUE_TYPES, SEVERITIES, Issue, IssueType, Severity, TriageRecord
from triage.taxonomy import components_for

Predictor = Callable[[Issue], Mapping[str, object]]

# Below this self-reported confidence, a human looks before routing acts.
# Self-reported confidence is uncalibrated; this number is a starting point.
REVIEW_THRESHOLD = 0.6

# Long bodies (stack traces, pasted logs) cost tokens and rarely change the
# classification. The head of the body carries the template answers.
MAX_BODY_CHARS = 6000


class TriageError(ValueError):
    """The model's output could not be turned into a valid record."""


def triage(issue: Issue, predictor: Predictor) -> TriageRecord:
    """Triage one issue. Never raises for model trouble: returns a failed record."""
    body = issue.body or ""
    if len(body) > MAX_BODY_CHARS:
        issue = issue.model_copy(update={"body": body[:MAX_BODY_CHARS] + "\n[truncated]"})
    try:
        raw = predictor(issue)
    except Exception as exc:  # the model boundary: network, quota, parse errors
        return failed_record(issue, f"model call failed: {type(exc).__name__}: {exc}")
    try:
        return build_record(issue, raw)
    except TriageError as exc:
        return failed_record(issue, str(exc))


def build_record(issue: Issue, raw: Mapping[str, object]) -> TriageRecord:
    issue_type = _choice(raw.get("issue_type"), ISSUE_TYPES, "issue_type")
    severity = _choice(raw.get("severity"), SEVERITIES, "severity")
    confidence = _confidence(raw.get("confidence"))
    has_repro = raw.get("has_reproduction_steps")
    if not isinstance(has_repro, bool):
        raise TriageError(f"has_reproduction_steps is not a bool: {has_repro!r}")
    summary = raw.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""

    return TriageRecord(
        repo=issue.repo,
        number=issue.number,
        issue_type=cast(IssueType, issue_type),
        component=_component(raw.get("component"), issue.repo),
        severity=cast(Severity, severity),
        has_reproduction_steps=has_repro,
        summary=summary,
        confidence=confidence,
        needs_human_review=confidence < REVIEW_THRESHOLD or issue_type == "other",
    )


def failed_record(issue: Issue, error: str) -> TriageRecord:
    return TriageRecord(
        repo=issue.repo,
        number=issue.number,
        issue_type=None,
        component=None,
        severity=None,
        has_reproduction_steps=None,
        summary="",
        confidence=0.0,
        needs_human_review=True,
        error=error,
    )


def _choice(value: object, allowed: tuple[str, ...], field: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    raise TriageError(f"{field} not in {allowed}: {value!r}")


def _component(value: object, repo: str) -> str | None:
    """A component outside the repo's vocabulary is dropped, not an error."""
    if not isinstance(value, str):
        return None
    normalised = value.strip().lower()
    return normalised if normalised in components_for(repo) else None


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TriageError(f"confidence is not a number: {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise TriageError(f"confidence is not a number: {value!r}") from None
    if number != number:  # NaN
        raise TriageError("confidence is NaN")
    return min(max(number, 0.0), 1.0)
