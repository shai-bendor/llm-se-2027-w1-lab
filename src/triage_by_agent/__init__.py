"""A reference triage implementation, for comparison with your own.

    from triage import ...             # yours, from Exercise A
    from triage_by_agent import ...    # this one

Triage takes one GitHub issue and produces one validated `TriageRecord`. That
is all it does. It does not decide where the issue goes.
"""

from triage_by_agent.extract import Triager
from triage_by_agent.schema import IssueType, Severity, TriageRecord
from triage_by_agent.stub import StubTriager

__all__ = [
    "IssueType",
    "Severity",
    "StubTriager",
    "TriageRecord",
    "Triager",
]
