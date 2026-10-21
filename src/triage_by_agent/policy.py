"""Business policy: what we have committed to, per severity and per type.

These are commitments the organisation made. They are not decisions the
program makes and they are not predictions the model makes — which is why
they live here, in one place, rather than being spelled out at each call site.
"""

from __future__ import annotations

from typing import Any

from triage_by_agent.schema import IssueType, Severity

# Hours to first response, by severity.
SLA_HOURS: dict[Severity, int] = {
    "critical": 4,
    "high": 24,
    "medium": 72,
    "low": 168,
}

# Which team owns an issue, by type.
QUEUE_BY_TYPE: dict[IssueType, str] = {
    "bug": "engineering",
    "enhancement": "product",
    "documentation": "docs",
    "question": "support",
    "meta": "maintainers",
}

# Where an issue goes when we cannot tell what it is.
CLARIFY_QUEUE = "triage-clarify"

# Fallback for the batch path, where the prediction has not been validated.
DEFAULT_SLA_HOURS = 72


def sla_for(severity: Severity) -> int:
    """Hours to first response for this severity.

    The KeyError is deliberate. A severity outside the vocabulary means
    something upstream failed to validate, and that is worth a stack trace
    rather than a plausible-looking default that nobody ever notices.
    """
    return SLA_HOURS[severity]


def sla_for_raw(raw: dict[str, Any]) -> int:
    """SLA lookup for the batch path, straight from the raw prediction.

    The batch path has the model output in hand and does not build a record
    for every issue, so this reads the field directly.
    """
    ticket_priority = raw["severity"]
    return SLA_HOURS.get(ticket_priority, DEFAULT_SLA_HOURS)


def queue_for(issue_type: IssueType) -> str:
    """The owning team for this issue type."""
    return QUEUE_BY_TYPE[issue_type]
