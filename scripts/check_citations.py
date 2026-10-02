#!/usr/bin/env python3
# AI-ASSISTED: fail when a Markdown file cites a Python test file or test that does not exist.
"""Fail when a Markdown file cites a missing Python test as `path.py::name`.

    check_citations.py [FILE ...]

Checks each citation in backticks: `api/tests/unit/test_x.py::test_y`, a class and a method
(`path.py::TestX::test_y`; each name defined in the file), and the short form `::test_z`, which
names another test of the file cited last on the same line. A path that is not a tracked file
from the repository root may be the unique tracked file that ends with it (`unit/test_x.py`).
Without arguments it reads every tracked Markdown file except the AI-LOG entries under
docs/ai-log/, which record the tests as they were when each PR merged. Exit status: 0 when every
citation resolves, 1 otherwise.
"""

import argparse
import ast
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

CODE = re.compile(r"`([^`\s]+)`")
NAME = r"[A-Za-z_]\w*(?:\[[^\]]*\])?"  # a parametrized id such as test_x[redis] names test_x
CITATION = re.compile(rf"(?P<path>[\w./-]+\.py)?(?P<names>(?:::{NAME})+)")
HISTORY = "docs/ai-log/"


def tracked(pattern: str) -> list[str]:
    """The tracked files that match a glob, as paths from the repository root."""
    return subprocess.run(
        ["git", "ls-files", "--", pattern],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


class Repository:
    """The tracked Python files of the working folder's repository, and what each defines."""

    def __init__(self) -> None:
        self.files = frozenset(tracked("*.py"))
        self._definitions: dict[str, frozenset[str]] = {}

    def resolve(self, path: str) -> str | None:
        """The tracked file a cited path names: itself, or the unique file that ends with it."""
        if path in self.files:
            return path
        ending = [name for name in self.files if name.endswith(f"/{path}")]
        return ending[0] if len(ending) == 1 else None

    def definitions(self, path: str) -> frozenset[str]:
        """The classes and functions the file defines at any depth, and its module-level names
        (a Hypothesis state machine's test case is ``TestMachine = Machine.TestCase``)."""
        if path not in self._definitions:
            tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
            kinds = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            names = {node.name for node in ast.walk(tree) if isinstance(node, kinds)}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            self._definitions[path] = frozenset(names)
        return self._definitions[path]


def problems(markdown: Path, repo: Repository) -> Iterator[str]:
    """One message per citation in the file that names a missing file or definition."""
    for number, line in enumerate(markdown.read_text(encoding="utf-8").splitlines(), 1):
        last: str | None = None  # the file cited last on this line, for a short ::name
        for code in CODE.findall(line):
            if (found := CITATION.fullmatch(code)) is None:
                continue
            where = f"{markdown}:{number}: `{code}`"
            if (path := found["path"]) is not None:
                last = repo.resolve(path)
                if last is None:
                    yield f"{where}: no tracked file, or more than one, is {path}"
                    continue
            elif last is None:
                yield f"{where}: no cited file before it on the line"
                continue
            names = [re.sub(r"\[.*", "", name) for name in found["names"].split("::")[1:]]
            missing = [name for name in names if name not in repo.definitions(last)]
            if missing:
                yield f"{where}: {last} defines no {', '.join(missing)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="Markdown files (default: tracked)")
    args = parser.parse_args(argv)
    files = args.files or [Path(name) for name in tracked("*.md") if not name.startswith(HISTORY)]
    repo = Repository()
    found = [message for markdown in files for message in problems(markdown, repo)]
    for message in found:
        print(message, file=sys.stderr)
    if found:
        return 1
    print(f"{len(files)} Markdown files: every test citation resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
