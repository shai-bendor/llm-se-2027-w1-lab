"""Per-repo component vocabularies.

These mirror the `component_labels` keys in `config/repos.toml` (a test keeps
them in step). Components are NOT shared across repos: hono's "middleware" and
litestar's "openapi" are different kinds of thing, so each repo gets its own
closed list and anything outside it becomes None.
"""

from __future__ import annotations

COMPONENTS: dict[str, tuple[str, ...]] = {
    "litestar": ("openapi", "dto", "di", "testing", "cli"),
    "hono": ("middleware", "testing"),
    "textual": (),
}


def components_for(repo: str) -> tuple[str, ...]:
    """The allowed components for `repo`; empty for unknown repos."""
    return COMPONENTS.get(repo.lower(), ())
