# AI-ASSISTED: the files a branch changes since its merge base, for the pull-request checks.
"""The files a branch changes since its merge base with a base commit.

Shared by scripts/check_pr.py and scripts/review_budget.py. A file is generated when
.gitattributes at the head commit marks it ``linguist-generated``; the size counts skip it.
"""

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Change:
    status: str  # A, C, D, M, R or T: the first letter of git's status
    path: str  # the path at the head commit; for a deleted file, its last path
    old_path: str | None  # the source of a rename or copy
    lines: int | None  # added plus deleted lines; None for a binary file
    generated: bool


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "--literal-pathspecs", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def merge_base(base: str, head: str) -> str:
    return git("merge-base", base, head).strip()


def changes(start: str, head: str) -> list[Change]:
    """Return every file changed from ``start`` to ``head``, with renames detected."""
    names = git("diff", "-z", "-M", "--name-status", start, head).split("\0")
    stats = git("diff", "-z", "-M", "--numstat", start, head).split("\0")
    entries: list[tuple[str, str, str | None, int | None]] = []
    while names[0]:
        status = names.pop(0)[0]
        old_path = names.pop(0) if status in "RC" else None
        path = names.pop(0)
        added, deleted, numstat_path = stats.pop(0).split("\t")
        if not numstat_path:  # a rename or copy: the two paths follow as their own fields
            del stats[:2]
        lines = None if added == "-" else int(added) + int(deleted)
        entries.append((status, path, old_path, lines))
    generated = _generated([path for _, path, _, _ in entries], head)
    return [Change(*entry, generated=entry[1] in generated) for entry in entries]


def _generated(paths: list[str], head: str) -> set[str]:
    if not paths:
        return set()
    fields = git("check-attr", "-z", f"--source={head}", "linguist-generated", "--", *paths)
    values = fields.split("\0")
    return {values[i] for i in range(0, len(values) - 2, 3) if values[i + 2] in {"set", "true"}}
