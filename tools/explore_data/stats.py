"""Distributions over whatever set of issues is currently selected.

Everything here is computed on the *filtered* set, so the dashboard and the
issue list always describe the same population: click a bar, the filter
changes, every number moves.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Sequence

from store import NO_VALUE, Issue

# Reading speed used to turn word counts into a minutes estimate. Generous for
# technical prose with code in it; it is a scale marker, not a measurement.
WORDS_PER_MINUTE = 180

CHAR_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-500", 0, 500),
    ("500-1k", 500, 1_000),
    ("1k-2k", 1_000, 2_000),
    ("2k-4k", 2_000, 4_000),
    ("4k-8k", 4_000, 8_000),
    ("8k+", 8_000, 10**9),
)

COMMENT_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0", 0, 1),
    ("1-2", 1, 3),
    ("3-5", 3, 6),
    ("6-10", 6, 11),
    ("11+", 11, 10**9),
)


def _counted(values: Sequence[str], limit: int | None = None) -> list[dict[str, Any]]:
    counter = Counter(values)
    items = counter.most_common(limit) if limit else sorted(counter.items())
    return [{"key": key, "count": count} for key, count in items]


def _bucketed(
    values: Sequence[int], buckets: tuple[tuple[str, int, int], ...]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, low, high in buckets:
        out.append(
            {"key": label, "count": sum(1 for v in values if low <= v < high)}
        )
    return out


def _percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def compute(issues: Sequence[Issue]) -> dict[str, Any]:
    total = len(issues)
    if total == 0:
        return {"total": 0, "charts": {}, "headline": {}, "coverage": []}

    chars = [i.signals.body_chars for i in issues]
    words = sum(i.signals.body_words for i in issues)
    labelled = sum(1 for i in issues if i.gold.get("gold_type"))
    any_label = sum(1 for i in issues if i.labels)
    templated = sum(1 for i in issues if i.signals.template_sections > 0)
    with_code = sum(1 for i in issues if i.signals.code_blocks > 0)
    closed = [i.days_to_close for i in issues if i.days_to_close is not None]

    # Gold coverage per repo: the single most important number for anyone
    # planning an annotation pass, and the one the snapshot hides.
    coverage: list[dict[str, Any]] = []
    for repo in sorted({i.repo for i in issues}):
        subset = [i for i in issues if i.repo == repo]
        hit = sum(1 for i in subset if i.gold.get("gold_type"))
        coverage.append(
            {
                "repo": repo,
                "total": len(subset),
                "labelled": hit,
                "unlabelled": len(subset) - hit,
                "percent": _percent(hit, len(subset)),
            }
        )

    # Which gold fields exist at all, across the selection.
    gold_fields: list[dict[str, Any]] = []
    for name in ("gold_type", "gold_component", "gold_has_reproduction_steps",
                 "gold_severity", "gold_duplicate_candidate"):
        present = sum(1 for i in issues if i.gold.get(name) is not None)
        gold_fields.append(
            {
                "key": name.removeprefix("gold_"),
                "count": present,
                "percent": _percent(present, total),
            }
        )

    charts: dict[str, Any] = {
        "repo": _counted([i.repo for i in issues]),
        "state": _counted([i.state for i in issues]),
        "type": _counted([str(i.gold.get("gold_type") or NO_VALUE) for i in issues]),
        "effort": [
            {"key": key, "count": sum(1 for i in issues if i.signals.effort == key)}
            for key in ("low", "medium", "high")
        ],
        "author": _counted([i.author_association or NO_VALUE for i in issues]),
        "month": _counted([i.created_at[:7] for i in issues if i.created_at]),
        "label": _counted([lab for i in issues for lab in i.labels], limit=15),
        "body_chars": _bucketed(chars, CHAR_BUCKETS),
        "comments": _bucketed([i.comments for i in issues], COMMENT_BUCKETS),
    }

    headline = {
        "total": total,
        "repos": len({i.repo for i in issues}),
        "gold_type_percent": _percent(labelled, total),
        "any_label_percent": _percent(any_label, total),
        "templated_percent": _percent(templated, total),
        "with_code_percent": _percent(with_code, total),
        "median_chars": int(statistics.median(chars)),
        "max_chars": max(chars),
        "reading_hours": round(words / WORDS_PER_MINUTE / 60, 1),
        "median_days_to_close": int(statistics.median(closed)) if closed else None,
        "open_percent": _percent(sum(1 for i in issues if i.state == "open"), total),
    }

    return {
        "total": total,
        "charts": charts,
        "headline": headline,
        "coverage": coverage,
        "gold_fields": gold_fields,
    }
