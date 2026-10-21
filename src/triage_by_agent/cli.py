"""Run the triage pipeline over a snapshot split.

    uv run python -m triage_by_agent.cli triage --split dev --limit 5
    uv run python -m triage_by_agent.cli triage --split dev --offline

`--offline` swaps the DSPy call for StubTriager: deterministic, no network, no
API spend. Use it whenever you want to exercise the whole program rather than
look at what the model actually says.

Only four fields of each issue are read: repo, number, title, body. The gold
columns are deliberately untouched — `gold_severity`,
`gold_has_reproduction_steps` and `gold_duplicate_candidate` are null in every
record in the snapshot, and `gold_component` is null in every dev record. There
is no ground truth here to score against, which is itself worth knowing.

`test.json` is sealed. This tool will refuse to open it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from triage_by_agent.schema import TriageRecord

SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "snapshot"
SEALED = "test"


class TriagerLike(Protocol):
    """What both Triager and StubTriager provide."""

    def triage(self, issue: dict[str, Any]) -> TriageRecord: ...

    def triage_raw(self, issue: dict[str, Any]) -> dict[str, Any]: ...


def load_split(split: str, data_dir: Path, limit: int | None) -> list[dict[str, Any]]:
    if split == SEALED:
        raise SystemExit(
            "test.json is sealed. Its only value is that nobody has looked at it. "
            "Use --split dev."
        )
    path = data_dir / f"{split}.json"
    if not path.exists():
        raise SystemExit(f"no such split: {path}")
    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return records if limit is None else records[:limit]


def make_triager(offline: bool) -> TriagerLike:
    if offline:
        from triage_by_agent.stub import StubTriager

        return StubTriager()

    from triage_by_agent.extract import Triager, configure

    configure()
    return Triager()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--split", default="dev", help="snapshot split (default: dev)")
    parser.add_argument("--data", type=Path, default=SNAPSHOT, help="snapshot directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use the deterministic stub instead of calling a model",
    )


def cmd_triage(args: argparse.Namespace) -> int:
    issues = load_split(args.split, args.data, args.limit)
    triager = make_triager(args.offline)
    for issue in issues:
        record = triager.triage(issue)
        print(
            f"{record.repo}#{record.issue_number:<6} "
            f"{record.issue_type:<13} {record.severity:<8} "
            f"repro={str(record.has_reproduction_steps):<5} "
            f"conf={record.confidence:.2f}"
        )
    print(f"\n{len(issues)} issues, {'offline stub' if args.offline else 'live model'}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from collections import Counter

    from triage_by_agent.router import process_batch

    issues = load_split(args.split, args.data, args.limit)
    triager = make_triager(args.offline)

    raws = [triager.triage_raw(issue) for issue in issues]
    print(f"triaged {len(raws)} issues, {'offline stub' if args.offline else 'live model'}")

    report = process_batch(raws, issues)

    queues = Counter(r.queue for r in report.routings)
    print("queues: " + "  ".join(f"{q} {n}" for q, n in sorted(queues.items())))
    print(f"escalated: {sum(1 for r in report.routings if r.escalate)}")
    print(f"duplicate pairs: {len(report.duplicate_pairs)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage_by_agent.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    triage = sub.add_parser("triage", help="triage each issue in a split")
    add_common_args(triage)
    triage.add_argument(
        "--limit",
        type=int,
        default=5,
        help="how many issues (default: 5 — a live run costs money)",
    )
    triage.set_defaults(func=cmd_triage)

    batch = sub.add_parser("batch", help="triage and route a whole split")
    add_common_args(batch)
    batch.add_argument(
        "--limit",
        type=int,
        default=None,
        help="how many issues (default: the whole split)",
    )
    batch.set_defaults(func=cmd_batch)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
