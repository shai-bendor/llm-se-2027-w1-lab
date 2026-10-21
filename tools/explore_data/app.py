"""explore_data -- a local, read-only browser for `data/snapshot/*.json`.

    uv run python tools/explore_data/app.py
    uv run python tools/explore_data/app.py --port 8123 --no-browser

Standard library only: no new dependencies, no build step, nothing fetched
from a CDN. It binds to 127.0.0.1 by default because it serves the contents
of files on this machine.

The API is four read-only GET endpoints:

    /api/meta                      splits on disk, facet values, date range
    /api/issues?<filters>          one page of matching issues (no bodies)
    /api/issue?split=&repo=&number=    one issue in full
    /api/stats?<filters>           distributions over the same filtered set
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stats import compute  # noqa: E402
from store import NO_VALUE, SEALED_SPLITS, Filters, Issue, Store, select  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _one(params: dict[str, list[str]], name: str, default: str = "") -> str:
    values = params.get(name)
    return values[0].strip() if values and values[0].strip() else default


def _many(params: dict[str, list[str]], name: str) -> frozenset[str]:
    """Repeated or comma-separated: ?repo=hono&repo=textual or ?repo=hono,textual."""
    out: set[str] = set()
    for raw in params.get(name, []):
        out.update(part.strip() for part in raw.split(",") if part.strip())
    return frozenset(out)


def _int(params: dict[str, list[str]], name: str) -> int | None:
    raw = _one(params, name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be an integer") from None


def _filters(params: dict[str, list[str]]) -> Filters:
    return Filters(
        repos=_many(params, "repo"),
        states=_many(params, "state"),
        types=_many(params, "type"),
        efforts=_many(params, "effort"),
        labels=_many(params, "label"),
        authors=_many(params, "author"),
        query=_one(params, "q").lower(),
        date_from=_one(params, "from"),
        date_to=_one(params, "to"),
        number_min=_int(params, "number_min"),
        number_max=_int(params, "number_max"),
        min_chars=_int(params, "min_chars"),
        max_chars=_int(params, "max_chars"),
    )


class Api:
    """The four endpoints, as plain functions over a `Store`."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def _issues(self, params: dict[str, list[str]]) -> list[Issue]:
        split = _one(params, "split", "dev")
        try:
            return self.store.load(split)
        except KeyError:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"unknown split {split!r}") from None
        except FileNotFoundError:
            raise ApiError(
                HTTPStatus.NOT_FOUND, f"data/snapshot/{split}.json is not on disk"
            ) from None

    def meta(self, params: dict[str, list[str]]) -> dict[str, Any]:
        """Facet values for the split, so the UI never invents a filter value."""
        split = _one(params, "split", "")
        payload: dict[str, Any] = {
            "splits": self.store.available(),
            "sealed": sorted(SEALED_SPLITS),
        }
        if not split:
            return payload
        issues = self._issues(params)
        dates = sorted(i.created_at[:10] for i in issues if i.created_at)
        payload["facets"] = {
            "repo": sorted({i.repo for i in issues}),
            "state": sorted({i.state for i in issues}),
            "type": sorted(
                {str(i.gold.get("gold_type") or NO_VALUE) for i in issues}
            ),
            "author": sorted({i.author_association for i in issues if i.author_association}),
            "label": sorted({lab for i in issues for lab in i.labels}),
            "effort": ["low", "medium", "high"],
            "date_min": dates[0] if dates else "",
            "date_max": dates[-1] if dates else "",
            "number_min": min((i.number for i in issues), default=0),
            "number_max": max((i.number for i in issues), default=0),
            "count": len(issues),
        }
        return payload

    def issues(self, params: dict[str, list[str]]) -> dict[str, Any]:
        matched = select(self._issues(params), _filters(params), _one(params, "sort", "created_desc"))
        offset = max(_int(params, "offset") or 0, 0)
        limit = min(_int(params, "limit") or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
        page = matched[offset : offset + limit]
        return {
            "total": len(matched),
            "offset": offset,
            "limit": limit,
            "items": [issue.summary() for issue in page],
            # The full ordered key list lets the reader walk prev/next through
            # the whole filtered set without paging the client.
            "order": [f"{i.repo}#{i.number}" for i in matched],
        }

    def issue(self, params: dict[str, list[str]]) -> dict[str, Any]:
        number = _int(params, "number")
        repo = _one(params, "repo")
        if number is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "number is required")
        for issue in self._issues(params):
            if issue.number == number and (not repo or issue.repo == repo):
                return issue.detail()
        raise ApiError(HTTPStatus.NOT_FOUND, f"no issue #{number} in this split")

    def stats(self, params: dict[str, list[str]]) -> dict[str, Any]:
        matched = select(self._issues(params), _filters(params), "created_desc")
        return compute(matched)


class Handler(BaseHTTPRequestHandler):
    server_version = "explore_data"
    protocol_version = "HTTP/1.1"

    def __init__(self, api: Api, *args: Any, **kwargs: Any) -> None:
        self.api = api
        super().__init__(*args, **kwargs)

    # Quieter than the default one-line-per-request log.
    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/"):
            sys.stderr.write(f"  {self.command} {self.path}\n")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # This serves local files to a local page; nothing else may embed it.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_static(self, name: str) -> None:
        # Resolve and confirm containment: a path from the network never
        # escapes static/.
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no such file: {name}"})
            return
        content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, target.read_bytes(), content_type)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        route = parsed.path

        routes = {
            "/api/meta": self.api.meta,
            "/api/issues": self.api.issues,
            "/api/issue": self.api.issue,
            "/api/stats": self.api.stats,
        }
        handler = routes.get(route)
        if handler is not None:
            try:
                self._send_json(HTTPStatus.OK, handler(params))
            except ApiError as error:
                self._send_json(error.status, {"error": error.message})
            except Exception as error:  # a crash must not take the server down
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"{type(error).__name__}: {error}"},
                )
            return

        if route in ("/", "/index.html"):
            self._send_static("index.html")
            return
        if route.startswith("/static/"):
            self._send_static(route.removeprefix("/static/"))
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no route {route}"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="explore_data", description="Browse data/snapshot in a local web app."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--snapshot-dir", type=Path, help="Override the data/snapshot location."
    )
    args = parser.parse_args(argv)

    store = Store(args.snapshot_dir)
    found = store.available()
    if not found:
        print("error: no snapshot files found", file=sys.stderr)
        return 1

    handler = partial(Handler, Api(store))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{server.server_port}/"
    splits = ", ".join(
        f"{s['name']}{' (SEALED)' if s['sealed'] else ''}" for s in found
    )
    print(f"explore_data serving {splits}")
    print(f"  {url}   (ctrl-c to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
