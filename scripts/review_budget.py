#!/usr/bin/env python3
# AI-ASSISTED: counts a branch's review input in tokens and flags a pull request that is too big.
"""Count the review input of a branch in tokens and fail when it reaches the limit.

    review_budget.py      compare HEAD with $BASE_SHA, or with origin/main when it is unset

The review input is the unified diff from merge-base(BASE, HEAD) to HEAD plus the full
contents at HEAD of every added, modified, renamed or copied file; a deleted file counts
only through its diff. Generated files (scripts/pr_changes.py) are left out. Tokens are
counted with tiktoken's o200k_base encoding, and the thresholds are the
[tool.review-budget] table of api/pyproject.toml. Exit status: 1 at the limit, else 0.
"""

import os
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

from pr_changes import changes, git, merge_base

ROOT = Path(__file__).resolve().parent.parent
LARGEST_FILES = 10
EXCEEDED = "Review budget exceeded: split this PR into smaller PRs"
# Each level above "ok", highest first, with the threshold that starts it.
LEVELS = {"error": "limit", "warning": "warning", "notice": "info"}


def budget() -> dict[str, int]:
    """Return the thresholds: ``info``, ``warning`` and ``limit``."""
    with (ROOT / "api" / "pyproject.toml").open("rb") as file:
        table: dict[str, int] = tomllib.load(file)["tool"]["review-budget"]
    return table


def review_input(base: str, head: str) -> dict[str, str]:
    """Return the review text of each changed file that is not generated, by its path."""
    start = merge_base(base, head)
    texts: dict[str, str] = {}
    for change in changes(start, head):
        if change.generated:
            continue
        paths = [change.old_path, change.path] if change.old_path else [change.path]
        text = git("diff", "-M", start, head, "--", *paths)
        if change.status != "D" and change.lines is not None:
            text += git("show", f"{head}:{change.path}")
        texts[change.path] = text
    return texts


def level(total: int, thresholds: dict[str, int]) -> str:
    return next((name for name, key in LEVELS.items() if total >= thresholds[key]), "ok")


def _o200k_count() -> Callable[[str], int]:
    import tiktoken  # noqa: PLC0415 - loads (and on first use downloads) the encoding

    encoding = tiktoken.get_encoding("o200k_base")
    return lambda text: len(encoding.encode_ordinary(text))


def _step_summary(total: int, tokens: dict[str, int], name: str) -> str:
    rows = sorted(tokens.items(), key=lambda item: (-item[1], item[0]))[:LARGEST_FILES]
    lines = [
        "### Review budget",
        "",
        "| File | Tokens |",
        "|---|---:|",
        f"| **Total ({len(tokens)} files, {name})** | **{total:,}** |",
        *(f"| `{path}` | {count:,} |" for path, count in rows),
    ]
    return "\n".join(lines) + "\n"


def main(count: Callable[[str], int] | None = None) -> int:
    thresholds = budget()
    texts = review_input(os.environ.get("BASE_SHA") or "origin/main", "HEAD")
    counter = count or _o200k_count()
    tokens = {path: counter(text) for path, text in texts.items()}
    total = sum(tokens.values())
    name = level(total, thresholds)
    print(f"review input: {total:,} tokens in {len(tokens)} files ({name})")
    if name != "ok":
        threshold = thresholds[LEVELS[name]]
        message = EXCEEDED if name == "error" else "Review input is large"
        print(
            f"::{name} title=Review budget::{message} ({total:,} tokens, {name} at {threshold:,})"
        )
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as file:
            file.write(_step_summary(total, tokens, name))
    return 1 if name == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
