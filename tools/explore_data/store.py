"""In-memory index over `data/snapshot/*.json`.

Read-only. The browser never writes to the snapshot, and nothing here takes a
value from the network and puts it anywhere but a filter expression.

Besides the fields the snapshot carries, every issue gets a set of *derived*
signals -- body length, code blocks, template sections, whether a traceback is
present, whether any label exists at all. Those are the things that decide how
expensive an issue is to annotate, which is the question this tool exists to
answer, and the snapshot does not record them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshot"

SPLITS: tuple[str, ...] = ("train", "dev", "test")
# `data/snapshot/MANIFEST.md` seals the test split. The app can still open it
# -- it is the user's data -- but it says so loudly and never loads it
# unasked.
SEALED_SPLITS: frozenset[str] = frozenset({"test"})

GOLD_FIELDS: tuple[str, ...] = (
    "gold_type",
    "gold_component",
    "gold_has_reproduction_steps",
    "gold_severity",
    "gold_duplicate_candidate",
)

NO_VALUE = "(none)"

_FENCE = re.compile(r"^\s*```", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6} +\S", re.MULTILINE)
_CHECKBOX = re.compile(r"^\s*[-*] \[[ xX]\]", re.MULTILINE)
_IMAGE = re.compile(r"!\[[^\]]*\]\(|<img\b", re.IGNORECASE)
_LINK = re.compile(r"https?://")
_TRACEBACK = re.compile(
    r"Traceback \(most recent call last\)|^\s+at [\w$.<>]+ \(|^\s*File \"",
    re.MULTILINE,
)


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _non_ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) > 127) / len(letters)


@dataclass(frozen=True)
class Signals:
    """Derived per-issue measures of how much work an annotator faces."""

    body_chars: int
    body_words: int
    code_blocks: int
    template_sections: int
    checkboxes: int
    has_images: bool
    has_links: bool
    has_traceback: bool
    non_ascii_ratio: float
    label_count: int
    has_gold_type: bool
    effort_score: int
    effort: Literal["low", "medium", "high"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "body_chars": self.body_chars,
            "body_words": self.body_words,
            "code_blocks": self.code_blocks,
            "template_sections": self.template_sections,
            "checkboxes": self.checkboxes,
            "has_images": self.has_images,
            "has_links": self.has_links,
            "has_traceback": self.has_traceback,
            "non_ascii_ratio": round(self.non_ascii_ratio, 3),
            "label_count": self.label_count,
            "has_gold_type": self.has_gold_type,
            "effort_score": self.effort_score,
            "effort": self.effort,
        }


# The formula is deliberately crude and is shown to the user in the UI: it is
# a reading-cost proxy, not a measurement. Length and code dominate because
# they decide how long a human spends before they can decide anything.
def _signals(body: str, labels: list[str], gold_type: str | None) -> Signals:
    chars = len(body)
    code_blocks = len(_FENCE.findall(body)) // 2
    sections = len(_HEADING.findall(body))
    ratio = _non_ascii_ratio(body)
    traceback = bool(_TRACEBACK.search(body))

    score = 0
    score += 0 if chars < 600 else 1 if chars < 2000 else 2 if chars < 6000 else 3
    score += 1 if code_blocks >= 3 else 0
    score += 1 if traceback else 0
    score += 1 if sections == 0 else 0  # free prose is harder than a template
    score += 1 if not labels else 0  # nothing to anchor a judgement on
    score += 1 if ratio > 0.05 else 0  # not written in English

    effort: Literal["low", "medium", "high"]
    effort = "low" if score <= 1 else "medium" if score <= 3 else "high"

    return Signals(
        body_chars=chars,
        body_words=len(body.split()),
        code_blocks=code_blocks,
        template_sections=sections,
        checkboxes=len(_CHECKBOX.findall(body)),
        has_images=bool(_IMAGE.search(body)),
        has_links=bool(_LINK.search(body)),
        has_traceback=traceback,
        non_ascii_ratio=ratio,
        label_count=len(labels),
        has_gold_type=gold_type is not None,
        effort_score=score,
        effort=effort,
    )


@dataclass(frozen=True)
class Issue:
    split: str
    repo: str
    number: int
    title: str
    body: str
    state: str
    labels: list[str]
    created_at: str
    closed_at: str | None
    comments: int
    author_association: str
    url: str
    gold: dict[str, Any]
    signals: Signals
    created: datetime | None = None
    days_to_close: int | None = None
    haystack: str = field(default="", repr=False)

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    def summary(self) -> dict[str, Any]:
        """The shape the issue list renders. Deliberately without the body."""
        return {
            "split": self.split,
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "labels": self.labels,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "comments": self.comments,
            "author_association": self.author_association,
            "url": self.url,
            "gold_type": self.gold.get("gold_type"),
            "effort": self.signals.effort,
            "body_chars": self.signals.body_chars,
        }

    def detail(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "body": self.body,
            "gold": self.gold,
            "signals": self.signals.as_dict(),
            "days_to_close": self.days_to_close,
        }


def _build(split: str, record: dict[str, Any]) -> Issue:
    body = str(record.get("body") or "")
    title = str(record.get("title") or "")
    raw_labels = record.get("labels") or []
    labels = [str(label) for label in raw_labels] if isinstance(raw_labels, list) else []
    gold = {name: record.get(name) for name in GOLD_FIELDS}
    gold_type = gold.get("gold_type")
    created = _iso_to_dt(record.get("created_at"))
    closed = _iso_to_dt(record.get("closed_at"))
    days = (closed - created).days if created and closed else None
    return Issue(
        split=split,
        repo=str(record.get("repo") or "?"),
        number=int(record.get("number") or 0),
        title=title,
        body=body,
        state=str(record.get("state") or "?"),
        labels=labels,
        created_at=str(record.get("created_at") or ""),
        closed_at=record.get("closed_at"),
        comments=int(record.get("comments") or 0),
        author_association=str(record.get("author_association") or ""),
        url=str(record.get("url") or ""),
        gold=gold,
        signals=_signals(body, labels, gold_type if isinstance(gold_type, str) else None),
        created=created,
        days_to_close=days,
        haystack=f"{title}\n{body}".lower(),
    )


class Store:
    """Lazily loads a split and keeps it in memory for the life of the server."""

    def __init__(self, snapshot_dir: Path | None = None) -> None:
        self.dir = snapshot_dir or SNAPSHOT_DIR
        self._cache: dict[str, list[Issue]] = {}

    def available(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in SPLITS:
            path = self.dir / f"{name}.json"
            if not path.exists():
                continue
            out.append(
                {
                    "name": name,
                    "sealed": name in SEALED_SPLITS,
                    "bytes": path.stat().st_size,
                    "loaded": name in self._cache,
                }
            )
        return out

    def load(self, split: str) -> list[Issue]:
        if split not in SPLITS:
            raise KeyError(f"unknown split {split!r}")
        cached = self._cache.get(split)
        if cached is not None:
            return cached
        path = self.dir / f"{split}.json"
        with path.open(encoding="utf-8") as handle:
            payload: Any = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"{path}: expected a JSON array")
        issues = [_build(split, r) for r in payload if isinstance(r, dict)]
        self._cache[split] = issues
        return issues


@dataclass(frozen=True)
class Filters:
    """Every filter the UI can express. All of them are AND-ed."""

    repos: frozenset[str] = frozenset()
    states: frozenset[str] = frozenset()
    types: frozenset[str] = frozenset()  # gold_type; NO_VALUE means unlabelled
    efforts: frozenset[str] = frozenset()
    labels: frozenset[str] = frozenset()
    authors: frozenset[str] = frozenset()
    query: str = ""
    date_from: str = ""
    date_to: str = ""
    number_min: int | None = None
    number_max: int | None = None
    min_chars: int | None = None
    max_chars: int | None = None

    def matches(self, issue: Issue) -> bool:
        if self.repos and issue.repo not in self.repos:
            return False
        if self.states and issue.state not in self.states:
            return False
        if self.types:
            gold_type = issue.gold.get("gold_type") or NO_VALUE
            if gold_type not in self.types:
                return False
        if self.efforts and issue.signals.effort not in self.efforts:
            return False
        if self.labels and not self.labels.intersection(issue.labels):
            return False
        if self.authors and issue.author_association not in self.authors:
            return False
        if self.date_from and issue.created_at[:10] < self.date_from:
            return False
        if self.date_to and issue.created_at[:10] > self.date_to:
            return False
        if self.number_min is not None and issue.number < self.number_min:
            return False
        if self.number_max is not None and issue.number > self.number_max:
            return False
        if self.min_chars is not None and issue.signals.body_chars < self.min_chars:
            return False
        if self.max_chars is not None and issue.signals.body_chars > self.max_chars:
            return False
        if self.query and self.query not in issue.haystack:
            return False
        return True


SORTS: dict[str, Any] = {
    "created_desc": (lambda i: i.created_at, True),
    "created_asc": (lambda i: i.created_at, False),
    "number_desc": (lambda i: (i.repo, i.number), True),
    "number_asc": (lambda i: (i.repo, i.number), False),
    "longest": (lambda i: i.signals.body_chars, True),
    "shortest": (lambda i: i.signals.body_chars, False),
    "effort": (lambda i: i.signals.effort_score, True),
    "comments": (lambda i: i.comments, True),
}


def select(issues: Iterable[Issue], filters: Filters, sort: str) -> list[Issue]:
    matched = [issue for issue in issues if filters.matches(issue)]
    key, reverse = SORTS.get(sort, SORTS["created_desc"])
    matched.sort(key=key, reverse=reverse)
    return matched
