"""Triage record: the contract between the stochastic and deterministic halves.

VOCABULARY. These names are the names.

    severity    how bad the issue is: low | medium | high | critical
    issue_type  what kind of issue it is
    component   which subsystem it touches, or None

Nothing in this package calls severity "priority", "urgency", "level" or
"impact". One concept, one name. If you find you need a second name for one of
these concepts, what you actually need is a second concept.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

IssueType = Literal["bug", "enhancement", "documentation", "question", "meta"]
Severity = Literal["low", "medium", "high", "critical"]

ISSUE_TYPES: tuple[IssueType, ...] = get_args(IssueType)
SEVERITIES: tuple[Severity, ...] = get_args(Severity)


class TriageRecord(BaseModel):
    """Structured result of triaging one issue.

    Every field here is validated. The model produces candidates; this type is
    where those candidates become data the rest of the program can rely on.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    issue_number: int
    repo: str
    issue_type: IssueType
    component: str | None = None
    severity: Severity
    has_reproduction_steps: bool
    confidence: float = Field(ge=0.0, le=1.0)


def coerce_severity(value: object) -> Severity:
    """Narrow an arbitrary model output to a Severity, or refuse.

    Case and surrounding whitespace are normalised, because a language model
    returns "High" about as often as "high". Anything outside the vocabulary
    raises: an unrecognised severity is a fact about the model's output, and
    guessing a default here would hide it from everyone downstream.
    """
    text = str(value).strip().lower()
    if text not in SEVERITIES:
        raise ValueError(f"not a severity: {value!r}")
    return text  # type: ignore[return-value]


def coerce_issue_type(value: object) -> IssueType:
    """Narrow an arbitrary model output to an IssueType, or refuse."""
    text = str(value).strip().lower()
    if text not in ISSUE_TYPES:
        raise ValueError(f"not an issue type: {value!r}")
    return text  # type: ignore[return-value]


def coerce_bool(value: object) -> bool:
    """Read a yes/no answer that arrived as prose."""
    return str(value).strip().lower() in {"true", "yes", "1"}


def coerce_component(value: object) -> str | None:
    """Collapse the many ways a model says "I don't know" into None."""
    text = str(value).strip().lower()
    return None if text in {"", "unknown", "none", "n/a"} else text


def coerce_confidence(value: object) -> float:
    """Read a probability, clamped, defaulting to zero when it is not a number.

    Zero is the safe default here in a way it is not for severity: a
    confidence we could not parse is a confidence we do not have.
    """
    try:
        return max(0.0, min(1.0, float(str(value).strip())))
    except ValueError:
        return 0.0
