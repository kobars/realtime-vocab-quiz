#!/usr/bin/env python3
# AI-ASSISTED: fail a JUnit XML report that ran no tests or skipped other tests than expected.
"""Fail unless a JUnit XML report ran tests and skipped exactly the expected ones.

    check_junit_skips.py REPORT [--expect N] [--reason PREFIX]

A test that skips passes pytest, so a suite can stop running without failing; this check
catches it. Every skip message must start with PREFIX. Exit status: 0 as expected, 1 not.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree as ET


def read(report: Path) -> tuple[int, list[tuple[str, str]]]:
    """Return the number of test cases and the (test id, message) of each skipped one."""
    root = ET.parse(report).getroot()  # noqa: S314 - the report of our own test run
    cases = list(root.iter("testcase"))
    skipped = [
        (f"{case.get('classname')}::{case.get('name')}", skip.get("message", ""))
        for case in cases
        if (skip := case.find("skipped")) is not None
    ]
    return len(cases), skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="the JUnit XML file")
    parser.add_argument("--expect", type=int, default=0, help="how many tests may skip")
    parser.add_argument("--reason", default="", help="the start of every expected skip message")
    args = parser.parse_args(argv)
    total, skipped = read(args.report)
    expected = all(message.startswith(args.reason) for _, message in skipped)
    if total and len(skipped) == args.expect and expected:
        print(f"{args.report}: {total} tests, {len(skipped)} skipped as expected")
        return 0
    print(
        f"{args.report}: {total} tests, {len(skipped)} skipped; expected {args.expect}"
        f" skips starting with {args.reason!r}",
        file=sys.stderr,
    )
    for test, message in skipped:
        print(f"  {test}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
