"""Tests for the snapshot browser.

    uv run pytest tools/explore_data

They live beside the tool rather than under tests/ because `pyproject.toml`
points pytest at tests/ and pyright away from tools/ -- this file is the
tool's own check, and the lab's `uv run pytest` stays exactly what it was.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import Api, ApiError  # noqa: E402
from stats import compute  # noqa: E402
from store import Filters, Store, select  # noqa: E402

ISSUES = [
    {
        "repo": "hono", "number": 10, "title": "Crash in router", "state": "open",
        "body": "### Steps\n\n```js\nfoo()\n```\n\nTraceback (most recent call last)\n" + "x" * 3000,
        "labels": ["bug"], "created_at": "2025-03-01T00:00:00Z", "closed_at": None,
        "comments": 4, "author_association": "NONE", "url": "u", "gold_type": "bug",
        "gold_component": None, "gold_has_reproduction_steps": None,
        "gold_severity": None, "gold_duplicate_candidate": None,
    },
    {
        "repo": "textual", "number": 20, "title": "Add a dark theme", "state": "closed",
        "body": "short prose, no template, no labels",
        "labels": [], "created_at": "2025-06-15T00:00:00Z", "closed_at": "2025-06-20T00:00:00Z",
        "comments": 0, "author_association": "MEMBER", "url": "u", "gold_type": None,
        "gold_component": None, "gold_has_reproduction_steps": None,
        "gold_severity": None, "gold_duplicate_candidate": None,
    },
]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    (tmp_path / "dev.json").write_text(json.dumps(ISSUES), encoding="utf-8")
    (tmp_path / "test.json").write_text(json.dumps(ISSUES[:1]), encoding="utf-8")
    return Store(tmp_path)


@pytest.fixture
def api(store: Store) -> Api:
    return Api(store)


# ---------------------------------------------------------------- store

def test_derived_signals_describe_reading_cost(store: Store) -> None:
    bug, feature = store.load("dev")
    assert bug.signals.code_blocks == 1
    assert bug.signals.template_sections == 1
    assert bug.signals.has_traceback is True
    assert bug.signals.effort in ("medium", "high")
    # Short, but free prose with no labels at all: two points, so medium.
    # Length alone never decides the bucket.
    assert feature.signals.template_sections == 0
    assert feature.signals.effort_score == 2
    assert feature.signals.effort == "medium"
    assert feature.days_to_close == 5


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (Filters(repos=frozenset({"hono"})), [10]),
        (Filters(states=frozenset({"closed"})), [20]),
        (Filters(types=frozenset({"(none)"})), [20]),
        (Filters(types=frozenset({"bug"})), [10]),
        (Filters(query="dark theme"), [20]),
        (Filters(date_from="2025-05-01"), [20]),
        (Filters(date_to="2025-05-01"), [10]),
        (Filters(number_min=15), [20]),
        (Filters(max_chars=100), [20]),
        (Filters(authors=frozenset({"MEMBER"})), [20]),
        (Filters(labels=frozenset({"bug"})), [10]),
        (Filters(repos=frozenset({"hono"}), states=frozenset({"closed"})), []),
    ],
)
def test_each_filter_selects_what_it_says(
    store: Store, filters: Filters, expected: list[int]
) -> None:
    got = [i.number for i in select(store.load("dev"), filters, "number_asc")]
    assert got == expected


def test_sort_orders_are_stable(store: Store) -> None:
    issues = store.load("dev")
    assert [i.number for i in select(issues, Filters(), "created_desc")] == [20, 10]
    assert [i.number for i in select(issues, Filters(), "longest")] == [10, 20]


def test_the_sealed_split_is_marked_but_not_loaded(store: Store) -> None:
    by_name = {s["name"]: s for s in store.available()}
    assert by_name["test"]["sealed"] is True
    assert by_name["test"]["loaded"] is False, "listing a split must not read it"
    assert by_name["dev"]["sealed"] is False


# ---------------------------------------------------------------- stats

def test_stats_describe_the_filtered_set(store: Store) -> None:
    out = compute(store.load("dev"))
    assert out["total"] == 2
    assert out["headline"]["gold_type_percent"] == 50.0
    assert {c["repo"]: c["labelled"] for c in out["coverage"]} == {"hono": 1, "textual": 0}
    # gold_type is the only gold field the snapshot actually fills in.
    present = {f["key"]: f["count"] for f in out["gold_fields"]}
    assert present == {"type": 1, "component": 0, "has_reproduction_steps": 0,
                       "severity": 0, "duplicate_candidate": 0}
    assert {r["key"]: r["count"] for r in out["charts"]["type"]} == {"bug": 1, "(none)": 1}


def test_stats_on_an_empty_selection_do_not_divide_by_zero() -> None:
    assert compute([])["total"] == 0


# ------------------------------------------------------------------ api

def test_issues_endpoint_pages_but_returns_the_whole_order(api: Api) -> None:
    out = api.issues({"split": ["dev"], "limit": ["1"], "sort": ["number_asc"]})
    assert out["total"] == 2
    assert len(out["items"]) == 1
    assert out["order"] == ["hono#10", "textual#20"]
    assert "body" not in out["items"][0], "the list must not ship every body"


def test_issue_endpoint_returns_one_body(api: Api) -> None:
    out = api.issue({"split": ["dev"], "repo": ["hono"], "number": ["10"]})
    assert out["issue_number" if "issue_number" in out else "number"] == 10
    assert "Traceback" in out["body"]
    assert out["signals"]["has_traceback"] is True


def test_unknown_split_and_missing_issue_are_api_errors(api: Api) -> None:
    with pytest.raises(ApiError):
        api.issues({"split": ["nope"]})
    with pytest.raises(ApiError):
        api.issue({"split": ["dev"], "number": ["999"]})
    with pytest.raises(ApiError):
        api.issues({"split": ["dev"], "number_min": ["abc"]})


def test_meta_lists_facets_without_inventing_values(api: Api) -> None:
    out = api.meta({"split": ["dev"]})
    assert out["sealed"] == ["test"]
    facets = out["facets"]
    assert facets["repo"] == ["hono", "textual"]
    assert facets["type"] == ["(none)", "bug"]
    assert facets["date_min"] == "2025-03-01"
    assert facets["number_max"] == 20


def test_stats_endpoint_honours_the_same_filters(api: Api) -> None:
    out = api.stats({"split": ["dev"], "repo": ["hono"]})
    assert out["total"] == 1
    assert out["headline"]["gold_type_percent"] == 100.0
