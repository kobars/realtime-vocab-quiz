#!/usr/bin/env python3
# AI-ASSISTED: internal-content guard for tracked files, commit messages and PR text.
"""Fail when tracked files, commit messages or PR text contain internal content.

    check_internal.py [PATH ...]       scan the given files, or every tracked file
    check_internal.py --commits RANGE  scan the commit messages in a git range
    check_internal.py --stdin          scan text read from standard input

Some patterns use a one-letter character class (``[a]``) so that this file
passes its own scan. Exit status: 0 clean, 1 findings, 2 git error.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

_I = re.IGNORECASE
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("task id", re.compile(r"\bK-\d{3}\b")),
    ("decision id", re.compile(r"\bQ(?:[1-9]|1\d|2[01])\b")),
    ("review id", re.compile(r"\bR-\d{1,2}\b")),
    ("course phrase", re.compile(r"\bcourse\s+(?:c[a]non|m[o]dule)\b", _I)),
    ("internal word", re.compile(r"\b(?:k[a]nban|recr[u]iter|interv[i]ew)\w*|\bc[a]non\b", _I)),
    ("docs product", re.compile(r"\bClaude\s+D[o]cs\b", _I)),
    ("artifact link", re.compile(r"claude\.ai/code/artifact", _I)),
    ("home path", re.compile(r"/(?:Users|home)/")),
    ("actor name", re.compile(r"\blead/c[l]aude", _I)),
    ("email address", re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")),
)


@dataclass(frozen=True)
class Finding:
    line: int
    rule: str
    match: str


def _allowed(rule: str, match: str) -> bool:
    return rule == "email address" and "noreply" in match.lower()


def scan_text(text: str) -> list[Finding]:
    """Return every internal-content match in ``text``, one per rule and span."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        claimed: list[tuple[int, int]] = []
        for rule, pattern in RULES:
            for found in pattern.finditer(line):
                start, end = found.span()
                if _allowed(rule, found[0]) or any(s < end and start < e for s, e in claimed):
                    continue
                claimed.append((start, end))
                findings.append(Finding(number, rule, found[0]))
    return findings


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _tracked_files() -> list[tuple[str, Path]]:
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    names = _git("-C", str(root), "ls-files", "-z").split("\0")
    return [(name, root / name) for name in names if name]


def _scan_files(files: Sequence[tuple[str, Path]]) -> Iterator[str]:
    for name, path in files:
        for finding in scan_text(name):
            yield f"{name}: file name: {finding.rule}: {finding.match}"
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for finding in scan_text(data.decode("utf-8", errors="replace")):
            yield f"{name}:{finding.line}: {finding.rule}: {finding.match}"


def _scan_commits(revision_range: str) -> Iterator[str]:
    log = _git("log", "--format=%h%x1f%B%x1e", revision_range)
    for record in log.split("\x1e"):
        sha, _, message = record.strip().partition("\x1f")
        for finding in scan_text(message):
            yield f"commit {sha}:{finding.line}: {finding.rule}: {finding.match}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--commits", metavar="RANGE", help="git revision range, e.g. A..B")
    mode.add_argument("--stdin", action="store_true", help="scan standard input")
    parser.add_argument("paths", nargs="*", type=Path, help="files to scan")
    args = parser.parse_args(argv)

    try:
        if args.stdin:
            text = sys.stdin.read()
            problems = [f"stdin:{f.line}: {f.rule}: {f.match}" for f in scan_text(text)]
        elif args.commits:
            problems = list(_scan_commits(args.commits))
        elif args.paths:
            problems = list(_scan_files([(str(path), path) for path in args.paths]))
        else:
            problems = list(_scan_files(_tracked_files()))
    except subprocess.CalledProcessError as error:
        print(f"check_internal: git failed: {error.stderr.strip()}", file=sys.stderr)
        return 2

    for problem in problems:
        print(problem)
    if problems:
        print(f"check_internal: {len(problems)} finding(s) of internal content", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
