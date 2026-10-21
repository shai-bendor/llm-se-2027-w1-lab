# Exercise B — the change under review

You have just received two things.

**`src/triage_by_agent/`** — a working triage implementation. It does the same
job as your Exercise A feature and nothing more: one issue in, one validated
`TriageRecord` out. It is not better than yours. It is just a second answer to
the same brief, and comparing the two is part of this exercise.

**`exercise-b/agent-change.diff`** — a proposed change to it. An agent was asked
to extend triage into a routing agent: take the triaged issue, decide which
queue it belongs in (in other words, to which team it should be assigned) and how fast it is due, and add a batch path so a whole
day's set of issues can be processed at once. The agent opened the change with this
description:

> Adds routing and batch processing. All tests pass, CI is green.

Your job is to decide whether you would approve it.

---

## Part 1 — Review (reading only)

Read the diff. Record every problem in `review-findings.md`.

**Do not run anything yet, and do not apply the diff.** Part 1 measures what
you catch by reading, which is the only thing that scales to a change you did
not write. You will get to run it in part 2.

```bash
less exercise-b/agent-change.diff        # or open it in your editor
```

Findings are locked when your instructor calls time. After that, do not edit or
add to your part 1 findings — part 2 goes in a separate section.

## Part 2 — Verify (running)

Now apply the change and find out what the tooling knows that you did not.

```
git apply exercise-b/agent-change.diff
uv run pytest
uv run pyright
uv run python -m triage_by_agent.cli batch --split dev --offline
```

`--offline` swaps the model for a deterministic stub, so the batch run costs
nothing and gives everyone in the room the same answer.

If `git apply` refuses because you edited the released package while reading,
put it back first:

```
git checkout -- src/triage_by_agent tests/exercise_b
git apply exercise-b/agent-change.diff
```

Write down, in the part 2 section of `review-findings.md`:

- what the tooling found that you did not
- what it did **not** find that you did
- for anything you missed: was it findable by reading, and what would have had
  to be different for you to have caught it?

That last question is the one the rest of the course is about.

---

## Undoing it

The change is applied to your working tree, not committed. To get back to the
released state:

```bash
git checkout -- src/triage_by_agent tests/exercise_b
```

Keep the change applied if you like — nothing later depends on it either way.
