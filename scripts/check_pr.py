#!/usr/bin/env python3
# AI-ASSISTED: pull-request guards: frozen test paths, size limit, commit rules and AI-LOG entry;
# Dependabot PRs skip the AI rules.
"""Check a pull request against the rules of AGENTS.md.

    check_pr.py --base SHA --head SHA --pr N [--author LOGIN] [--labels LABEL ...]

1. Frozen paths: the PR changes api/tests/acceptance/, api/tests/conftest.py or the
   [tool.pytest.ini_options] table of api/pyproject.toml only with the label acceptance-change.
2. Size: at most 400 changed lines, generated files (scripts/pr_changes.py) not counted,
   unless the label size-exception is present.
3. Commits: every commit but a merge has the AI-Assisted: trailer, and a subject of at most
   100 characters that does not start with fixup!, squash!, amend! or the word WIP.
4. The AI-LOG entry docs/ai-log/PR-<n>.md exists at the head commit.

A PR whose author is dependabot[bot] skips the trailer of rule 3 and rule 4: those rules
document AI-written code, and a bot writes these PRs. Every other rule still applies.

Every failure is printed as a GitHub error annotation. Exit status: 0 clean, 1 failures.
"""

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence

from pr_changes import Change, changes, git, merge_base

ACCEPTANCE_LABEL = "acceptance-change"
SIZE_LABEL = "size-exception"
MAX_CHANGED_LINES = 400
MAX_SUBJECT = 100
BAD_SUBJECT = re.compile(r"(fixup|squash|amend)!|WIP\b")
FROZEN_FOLDER = "api/tests/acceptance/"
FROZEN_FILE = "api/tests/conftest.py"
PYPROJECT = "api/pyproject.toml"
DEPENDABOT = "dependabot[bot]"


def _show(commit: str, path: str) -> str | None:
    try:
        return git("show", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        return None


def _pytest_settings(commit: str) -> object:
    text = _show(commit, PYPROJECT)
    return tomllib.loads(text or "").get("tool", {}).get("pytest", {}).get("ini_options")


def frozen_changes(diff: Sequence[Change], start: str, head: str) -> list[str]:
    """Return the frozen paths that the PR changes."""
    paths = {path for change in diff for path in (change.path, change.old_path) if path}
    frozen = sorted(p for p in paths if p.startswith(FROZEN_FOLDER) or p == FROZEN_FILE)
    if PYPROJECT in paths and _pytest_settings(start) != _pytest_settings(head):
        frozen.append(f"{PYPROJECT} [tool.pytest.ini_options]")
    return frozen


def changed_lines(diff: Sequence[Change]) -> int:
    return sum(change.lines or 0 for change in diff if not change.generated)


def commit_problems(start: str, head: str, *, need_trailer: bool) -> list[str]:
    log = git(
        "log",
        "-z",
        "--no-merges",
        "--format=%h%x1f%s%x1f%(trailers:key=AI-Assisted,valueonly)",
        f"{start}..{head}",
    )
    problems: list[str] = []
    for record in filter(None, log.split("\0")):
        sha, subject, trailer = record.split("\x1f")
        if need_trailer and not trailer.strip():
            problems.append(f"commit {sha} has no AI-Assisted: trailer")
        if BAD_SUBJECT.match(subject):
            problems.append(f"commit {sha} is a fixup, squash, amend or WIP commit: {subject}")
        if len(subject) > MAX_SUBJECT:
            problems.append(f"commit {sha} has a subject over {MAX_SUBJECT} characters")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the commit the PR merges into")
    parser.add_argument("--head", required=True, help="the PR's head commit")
    parser.add_argument("--pr", required=True, type=int, help="the PR number")
    parser.add_argument("--author", default="", help="the login of the PR's author")
    parser.add_argument("--labels", nargs="*", default=[], help="the PR's labels")
    args = parser.parse_args(argv)

    start = merge_base(args.base, args.head)
    diff = changes(start, args.head)
    failures: list[str] = []
    if (frozen := frozen_changes(diff, start, args.head)) and ACCEPTANCE_LABEL not in args.labels:
        failures.append(f"frozen paths changed without the {ACCEPTANCE_LABEL} label: {frozen}")
    lines = changed_lines(diff)
    if lines > MAX_CHANGED_LINES and SIZE_LABEL not in args.labels:
        failures.append(
            f"{lines} changed lines, over {MAX_CHANGED_LINES} (generated files not counted);"
            f" split the PR or add the {SIZE_LABEL} label"
        )
    ai_rules = args.author != DEPENDABOT
    failures += commit_problems(start, args.head, need_trailer=ai_rules)
    entry = f"docs/ai-log/PR-{args.pr}.md"
    if ai_rules and _show(args.head, entry) is None:
        failures.append(f"the AI-LOG entry {entry} is missing")

    for failure in failures:
        printable = failure.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        print(f"::error title=PR guards::{printable}")
    if not failures:
        print(f"PR guards passed: {lines} changed lines, generated files not counted")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
