"""Input and output types for triage.

`Issue` is what goes in; `TriageRecord` is what comes out and what routing
will consume. Both are validated at runtime because one side is written by
strangers and the other by a model.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

IssueType = Literal["bug", "enhancement", "documentation", "question", "other"]
Severity = Literal["low", "medium", "high", "critical"]

ISSUE_TYPES: tuple[str, ...] = get_args(IssueType)
SEVERITIES: tuple[str, ...] = get_args(Severity)


class Issue(BaseModel):
    """A GitHub issue as triage sees it.

    `extra="ignore"` is deliberate: snapshot records also carry `labels` and
    `gold_*` fields. Labels are where the gold type comes from, so letting the
    model see them would make triage look far better than it is on a truly
    new, unlabelled issue.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    repo: str
    number: int | None = None
    title: str
    body: str | None = None


class TriageRecord(BaseModel):
    """One structured triage decision, ready for a router to act on.

    When triage fails, the classification fields are None, `error` says why,
    and `needs_human_review` is True: a router should never have to guess.
    """

    model_config = ConfigDict(frozen=True)

    repo: str
    number: int | None
    issue_type: IssueType | None
    component: str | None
    severity: Severity | None
    has_reproduction_steps: bool | None
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_review: bool
    error: str | None = None
