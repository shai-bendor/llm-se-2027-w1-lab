"""Routing. Given a triaged issue, decide where it goes and how fast.

No model calls happen here, ever. This half of the pipeline is ordinary
software: given a validated record, the queue, the clock and the escalation
flag follow by rule. It is unit-testable and it is either correct or
incorrect, not "about 87% accurate".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from triage_by_agent.policy import (
    CLARIFY_QUEUE,
    QUEUE_BY_TYPE,
    queue_for,
    sla_for,
    sla_for_raw,
)
from triage_by_agent.schema import TriageRecord


@dataclass(frozen=True)
class Routing:
    """Where one issue goes, when it is due, and why."""

    queue: str
    sla_hours: int
    escalate: bool
    reason: str


@dataclass(frozen=True)
class BatchReport:
    """Aggregated routing outcome for a batch of issues."""

    routings: list[Routing]
    duplicate_pairs: list[tuple[int, int]]


def route(record: TriageRecord) -> Routing:
    """Route one validated record."""
    queue = queue_for(record.issue_type)
    sla = sla_for(record.severity)

    if record.issue_type == "bug" and not record.has_reproduction_steps:
        return Routing(
            queue=CLARIFY_QUEUE,
            sla_hours=sla,
            escalate=False,
            reason="bug without reproduction steps",
        )

    escalate = record.severity == "critical" or (
        record.severity == "high" and record.confidence < 0.6
    )
    return Routing(
        queue=queue, sla_hours=sla, escalate=escalate, reason="routed by type and severity"
    )


def route_raw(raw: dict[str, Any]) -> Routing:
    """Route straight from a raw prediction dict, skipping record construction.

    Used by the batch path, where we already have the model output in hand and
    building a TriageRecord for every issue is unnecessary overhead.
    """
    ticket_priority = raw["severity"]
    sla = sla_for_raw(raw)
    queue = QUEUE_BY_TYPE.get(raw["issue_type"], CLARIFY_QUEUE)
    escalate = ticket_priority == "critical"
    return Routing(queue=queue, sla_hours=sla, escalate=escalate, reason="batch routing")


def find_duplicates(issues: list[dict[str, Any]], threshold: float = 0.8) -> list[tuple[int, int]]:
    """Flag likely duplicate issues within a batch."""
    if len(issues) < 2:
        return []

    from triage_by_agent.similarity import similarity_score

    pairs: list[tuple[int, int]] = []
    for i, left in enumerate(issues):
        for j, right in enumerate(issues):
            if i >= j:
                continue
            if similarity_score(left["title"], right["title"]) >= threshold:
                pairs.append((left["number"], right["number"]))
    return pairs


def process_batch(raws: list[dict[str, Any]], issues: list[dict[str, Any]]) -> BatchReport:
    """Route a whole batch and report duplicates within it."""
    if not raws:
        return BatchReport(routings=[], duplicate_pairs=[])

    routings = [route_raw(raw) for raw in raws]

    # Preserve first-seen order while removing repeats.
    by_number = {issue["number"]: issue for issue in issues}
    unique_issues = [by_number[n] for n in dict.fromkeys(issue["number"] for issue in issues)]

    return BatchReport(routings=routings, duplicate_pairs=find_duplicates(unique_issues))
