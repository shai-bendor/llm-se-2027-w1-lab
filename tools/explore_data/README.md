# explore_data

A local, read-only browser for `data/snapshot/*.json`: read the issues one at a
time, filter them on metadata, and see the distributions behind them.

```bash
uv run python tools/explore_data/app.py            # opens http://127.0.0.1:8787/
uv run python tools/explore_data/app.py --port 9000 --no-browser
uv run pytest tools/explore_data                   # the tool's own tests
```

Standard library only — no new dependencies, no build step, nothing loaded
from a CDN. It binds to `127.0.0.1` because it serves the contents of files on
this machine.

## What it is for

The question behind the app is **how hard would it be to annotate this data**,
by hand or automatically. So beside the fields the snapshot carries, every
issue is measured for reading cost — body length, code blocks, whether an
issue template was followed, whether any label exists at all — and the
dashboard leads with what is *missing*:

- `gold_type` is present on 42% of dev and 45% of train.
- `gold_component` is present on 2 issues out of 720 in train, 0 in dev.
- `gold_severity`, `gold_has_reproduction_steps` and `gold_duplicate_candidate`
  are empty everywhere. Anyone who wants those fields creates them.
- Coverage is wildly uneven per project: in dev, litestar is 91% labelled,
  hono 35%, textual 0%.

## Browse

Filter rail, result list, one issue in the reader. Filters are AND-ed and
cover project, status, gold type, annotation effort, author association,
created date, issue number range, body size, and a github label; free text
searches title and body and is highlighted in the reader.

`j`/`k` (or the arrow keys) move through the filtered set, `/` focuses search.
The URL hash holds the whole state — filters, sort, open issue — so a view is
a link you can paste into `review-findings.md`.

## Statistics

Every chart describes the **current filter**, and clicking a bar toggles that
value as a filter, so the two views always describe the same population.
Charts can be switched to tables (and that choice is in the URL too).

"Annotation effort" is derived here, not in the data: a reading-cost proxy
scored from body length, code blocks, stack traces, missing template headings,
missing labels, and non-English text. The exact formula is printed at the
bottom of the dashboard.

## The sealed split

`data/snapshot/MANIFEST.md` seals `test.json`. The app lists it, says SEALED in
red, and loads nothing until you click through the warning — including when a
`#split=test` link is what opened the page.

## Layout

| File | Role |
|---|---|
| `app.py` | HTTP server and the four read-only GET endpoints |
| `store.py` | loading, derived signals, filtering, sorting |
| `stats.py` | distributions over the filtered set |
| `static/` | the page: `index.html`, `app.js`, `styles.css` |
| `test_explore_data.py` | tests for the above |

### API

    /api/meta?split=dev                splits on disk, facet values, ranges
    /api/issues?split=dev&repo=hono…   one page of matches, plus the full order
    /api/issue?split=dev&repo=&number= one issue in full
    /api/stats?split=dev&…             distributions over the same filters

### A note on the issue text

Issue bodies are written by anonymous strangers, so the client treats them as
data: nothing from a body reaches the DOM through `innerHTML`. The markdown
renderer builds nodes, links are rendered only for `http(s)` and carry
`rel="noopener noreferrer nofollow"`, remote images are never fetched (the
reference is shown as text), and HTML comments — invisible on github — are
shown, because what a reader cannot see is exactly what an annotator misses.
