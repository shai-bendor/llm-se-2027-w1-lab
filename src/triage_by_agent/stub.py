"""A deterministic stand-in for the model, so the pipeline can be run for free.

`StubTriager` has the same contract as `Triager` and returns a valid
`TriageRecord`, but it never calls a model. It exists so that forty people can
exercise the whole program over all 240 dev issues without forty API keys and
without one lecture room's worth of live calls.

It is a stand-in, not a model: the records it returns are plausible, not
correct. Do not evaluate anything against them.

Determinism comes from hashlib, NOT from the builtin hash(), whose string
hashing is salted per process — the same issue must produce the same record on
every machine and on every run, or nobody can compare anything.
"""

from __future__ import annotations

import hashlib
from typing import Any

from triage_by_agent.schema import (
    ISSUE_TYPES,
    SEVERITIES,
    IssueType,
    Severity,
    TriageRecord,
)

# Words that suggest the author told us how to reproduce the problem.
_REPRO_MARKERS = ("steps to reproduce", "reproduction", "repro:", "to reproduce", "```")


def _digest(issue: dict[str, Any]) -> bytes:
    key = f"{issue['repo']}#{issue['number']}".encode()
    return hashlib.sha1(key).digest()


class StubTriager:
    """Same shape as Triager, no network, same answer every time."""

    def triage_raw(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Prediction as a plain dict, for the batch path."""
        record = self.triage(issue)
        return {
            "issue_number": record.issue_number,
            "repo": record.repo,
            "issue_type": record.issue_type,
            "component": record.component,
            "severity": record.severity,
            "has_reproduction_steps": record.has_reproduction_steps,
            "confidence": record.confidence,
        }

    def triage(self, issue: dict[str, Any]) -> TriageRecord:
        d = _digest(issue)
        body = str(issue.get("body", ""))

        issue_type: IssueType = ISSUE_TYPES[d[0] % len(ISSUE_TYPES)]
        severity: Severity = SEVERITIES[d[1] % len(SEVERITIES)]

        return TriageRecord(
            issue_number=int(issue["number"]),
            repo=str(issue["repo"]),
            issue_type=issue_type,
            component=None,
            severity=severity,
            has_reproduction_steps=any(m in body.lower() for m in _REPRO_MARKERS),
            # 0.50 to 0.99, stable per issue.
            confidence=round(0.50 + (d[2] % 50) / 100.0, 2),
        )
