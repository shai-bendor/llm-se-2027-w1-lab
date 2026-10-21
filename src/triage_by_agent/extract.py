"""The LLM boundary. Types stop here; runtime validation takes over.

`Prediction` below is an assertion about a shape we do not control. The model
is free to ignore it, which is exactly why every field goes through a coercer
in `schema` before it reaches `TriageRecord`. The Protocol documents what we
asked for; the coercers deal with what we got.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, cast

import dspy
from dotenv import find_dotenv, load_dotenv

from triage_by_agent.schema import (
    TriageRecord,
    coerce_bool,
    coerce_component,
    coerce_confidence,
    coerce_issue_type,
    coerce_severity,
)


class TriageSignature(dspy.Signature):
    """Classify a GitHub issue for triage."""

    title: str = dspy.InputField()
    body: str = dspy.InputField()
    issue_type: str = dspy.OutputField(desc="bug, enhancement, documentation, question, or meta")
    component: str = dspy.OutputField(desc="affected subsystem, or 'unknown'")
    severity: str = dspy.OutputField(desc="low, medium, high, or critical")
    has_reproduction_steps: str = dspy.OutputField(desc="true or false")
    confidence: str = dspy.OutputField(desc="number between 0 and 1")


class Prediction(Protocol):
    """The five fields we asked the model for. All of them arrive as text."""

    issue_type: str
    component: str
    severity: str
    has_reproduction_steps: str
    confidence: str


class Predictor(Protocol):
    def __call__(self, *, title: str, body: str) -> Prediction: ...


def configure() -> None:
    # Credentials live in the .env at the repo root. find_dotenv walks up from
    # this file until it hits one, so this works from any working directory and
    # `uv run --env-file` is optional. Anything already exported wins:
    # load_dotenv does not override the real environment.
    load_dotenv(find_dotenv(usecwd=False))
    dspy.configure(lm=dspy.LM(os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4-6")))


class Triager:
    def __init__(self, predictor: Predictor | None = None) -> None:
        # The predictor is injectable so the boundary can be tested without a
        # network call. Default is the real thing.
        #
        # The cast is the seam, stated out loud: dspy.Predict.__call__ is
        # (...) -> Prediction, which promises nothing about the arguments and
        # nothing about which fields come back. We assert the shape here, once,
        # in the one place that is allowed to, and validate the result below.
        self._predict: Predictor = predictor or cast(Predictor, dspy.Predict(TriageSignature))

    def triage_raw(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Return the model prediction directly, for the batch path.

        Skips TriageRecord construction so batches stay fast.
        """
        pred = self._predict(title=issue["title"], body=issue["body"][:4000])
        return {
            "issue_number": issue["number"],
            "repo": issue["repo"],
            "issue_type": pred.issue_type,
            "component": pred.component,
            "severity": pred.severity,
            "has_reproduction_steps": pred.has_reproduction_steps,
            "confidence": pred.confidence,
        }

    def triage(self, issue: dict[str, Any]) -> TriageRecord:
        # Issue text is untrusted. It is passed as a field VALUE, never
        # concatenated into an instruction, and never near a shell.
        pred = self._predict(title=issue["title"], body=issue["body"][:4000])

        # Everything the model returned is a string of unknown shape. This is
        # the only place in the codebase where that is allowed to be true.
        # TriageRecord validates, so a bad prediction raises HERE rather than
        # silently flowing into the router three modules later.
        return TriageRecord(
            issue_number=int(issue["number"]),
            repo=str(issue["repo"]),
            issue_type=coerce_issue_type(pred.issue_type),
            component=coerce_component(pred.component),
            severity=coerce_severity(pred.severity),
            has_reproduction_steps=coerce_bool(pred.has_reproduction_steps),
            confidence=coerce_confidence(pred.confidence),
        )
