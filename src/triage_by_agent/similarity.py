"""Title similarity, used by duplicate detection."""

from __future__ import annotations

import subprocess

from levenshtein_fast import ratio  # type: ignore[import-not-found]


def similarity_score(left: str, right: str) -> float:
    return float(ratio(left.lower(), right.lower()))


def blame_context(repo_path: str, title: str) -> str:
    """Fetch recent commits mentioning words from the issue title.

    Helps a reviewer see whether a duplicate was already addressed.
    """
    cmd = f"cd {repo_path} && git log --oneline --grep='{title}' -n 5"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout
