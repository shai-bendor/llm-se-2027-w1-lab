"""Block credential-shaped strings from being committed.

Called by the pre-commit hook. Scans STAGED content only.

This is a blunt instrument on purpose. It will occasionally flag something
harmless. When it does, look carefully before you override it - the base rate
of "the scanner is wrong" is much lower than the base rate of "I was about to
publish a key".
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI key", re.compile(r"sk-(proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Google key", re.compile(r"AIza[A-Za-z0-9_\-]{30,}")),
    ("xAI key", re.compile(r"xai-[A-Za-z0-9]{32,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# .env.example legitimately contains placeholders shaped like keys.
ALLOW_SUBSTRINGS = ("xxxx", "XXXX")


def git(*args: str) -> str:
    # Decode explicitly: with bare text=True, Windows uses the locale codepage
    # (cp1252) and crashes on UTF-8 or binary content. errors="replace" keeps
    # binary files scannable, since every key pattern above is plain ASCII.
    out = subprocess.run(
        ["git", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return out.stdout


def staged_files() -> list[str]:
    output = git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [f for f in output.splitlines() if f.strip()]


def staged_content(path: str) -> str:
    return git("show", f":{path}")


def main() -> int:
    hits: list[str] = []
    for path in staged_files():
        if path.endswith((".png", ".jpg", ".gif", ".pdf", ".lock")):
            continue
        content = staged_content(path)
        for label, pattern in PATTERNS:
            for match in pattern.finditer(content):
                if any(a in match.group(0) for a in ALLOW_SUBSTRINGS):
                    continue
                line = content[: match.start()].count("\n") + 1
                hits.append(f"  {path}:{line}  {label}")

    if hits:
        print("COMMIT BLOCKED - credential-shaped strings found:\n")
        print("\n".join(hits))
        print(
            "\nIf this is a real key: remove it, then ROTATE IT. Assume anything\n"
            "that reached a commit object is already compromised.\n"
            "If it is genuinely a false positive: git commit --no-verify\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
