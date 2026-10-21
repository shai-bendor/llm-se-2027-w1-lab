"""Command line: one issue in, one triage record (JSON) out.

    uv run python -m triage.cli issue.json            # a file holding one issue object
    uv run python -m triage.cli -  < issue.json       # the same, from stdin
    uv run python -m triage.cli --split dev --index 3
    uv run python -m triage.cli --split dev --index 0 --count 20   # JSON Lines

Issue text is only ever passed to the model as data. Nothing here touches a shell.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from triage.record import triage
from triage.schema import Issue, TriageRecord

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshot"
# test.json is sealed: the CLI refuses to read it.
READABLE_SPLITS = ("train", "dev")


def load_issues(args: argparse.Namespace) -> list[Issue]:
    if args.split is not None:
        records: Any = json.loads((SNAPSHOT_DIR / f"{args.split}.json").read_text("utf-8"))
        chosen: list[Any] = records[args.index : args.index + args.count]
        if not chosen:
            raise SystemExit(f"no issues at index {args.index} in {args.split}.json")
        return [Issue.model_validate(item) for item in chosen]
    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text("utf-8")
    return [Issue.model_validate_json(text)]


def to_json(record: TriageRecord, *, indent: int | None) -> str:
    # ensure_ascii keeps output printable on any console encoding (cp1252 on Windows).
    return json.dumps(record.model_dump(), indent=indent, ensure_ascii=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="triage", description="Triage a GitHub issue into a structured record."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("path", nargs="?", help="JSON file with one issue, or - for stdin")
    source.add_argument("--split", choices=READABLE_SPLITS, help="read from data/snapshot")
    parser.add_argument("--index", type=int, default=0, help="first issue in the split")
    parser.add_argument("--count", type=int, default=1, help="how many issues from --index")
    parser.add_argument("--model", help="override LLM_MODEL")
    args = parser.parse_args(argv)

    try:
        issues = load_issues(args)
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"error: could not read issue: {exc}", file=sys.stderr)
        return 2

    load_dotenv()
    from triage.extract import make_predictor  # imports dspy; keep --help fast

    try:
        predictor = make_predictor(args.model)
    except KeyError:
        print("error: set LLM_MODEL in .env (see .env.example)", file=sys.stderr)
        return 2

    failed = False
    for issue in issues:
        record = triage(issue, predictor)
        failed = failed or record.error is not None
        print(to_json(record, indent=2 if len(issues) == 1 else None), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
