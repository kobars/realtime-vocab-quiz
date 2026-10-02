#!/usr/bin/env python3
# AI-ASSISTED: fail when a Markdown file cites a Python test file or test that does not exist.
"""Fail when a Markdown file cites a missing Python test as `path.py::name`.

    check_citations.py [FILE ...]

Checks each citation in backticks: `api/tests/unit/test_x.py::test_y`, a method of a class
(`path.py::TestX::test_y`, the method defined in that class's body), and the short form
`::test_z`, which names another test of the file cited last in the same paragraph or table row
(a full citation, or a bare `path.py`). The first name must be defined at the top of the file: a
class, a function, or a module-level name. A path that is not a tracked file from the repository
root may be the unique tracked file that ends with it (`unit/test_x.py`). Without arguments it
reads every tracked Markdown file except the AI-LOG entries under docs/ai-log/, which record the
tests as they were when each PR merged. It runs from the repository root wherever it is started.
Exit status: 0 when every citation resolves, 1 otherwise.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

CODE = re.compile(r"`([^`\s]+)`")
NAME = r"[A-Za-z_]\w*(?:\[[^\]]*\])?"  # a parametrized id such as test_x[redis] names test_x
CITATION = re.compile(rf"(?P<path>[\w./-]+\.py)?(?P<names>(?:::{NAME})*)")
HISTORY = "docs/ai-log/"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def tracked(pattern: str) -> list[str]:
    """The tracked files that match a glob and exist in the work tree, from the root."""
    return [name for name in git("ls-files", "--", pattern).splitlines() if Path(name).is_file()]


def scope(body: list[ast.stmt]) -> dict[str, list[ast.stmt]]:
    """The names a module or class body defines, each with the body it opens (a class's)."""
    names: dict[str, list[ast.stmt]] = {}
    for node in body:
        if isinstance(node, ast.ClassDef):
            names[node.name] = node.body
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names[node.name] = []
        elif isinstance(node, ast.Assign):  # a state machine's ``TestMachine = M.TestCase``
            names.update((target.id, []) for target in node.targets if isinstance(target, ast.Name))
    return names


class Repository:
    """The tracked Python files of the working folder's repository, and what each defines."""

    def __init__(self) -> None:
        self.files = frozenset(tracked("*.py"))
        self._modules: dict[str, list[ast.stmt]] = {}

    def resolve(self, path: str) -> str | None:
        """The tracked file a cited path names: itself, or the unique file that ends with it."""
        if path in self.files:
            return path
        ending = [name for name in self.files if name.endswith(f"/{path}")]
        return ending[0] if len(ending) == 1 else None

    def missing(self, path: str, names: Sequence[str]) -> str | None:
        """The leading part of ``A::b`` that the file does not define, or None."""
        if path not in self._modules:
            source = Path(path).read_text(encoding="utf-8")
            self._modules[path] = ast.parse(source, filename=path).body
        body = self._modules[path]
        for depth, name in enumerate(names, 1):
            defined = scope(body)
            if name not in defined:
                return "::".join(names[:depth])
            body = defined[name]
        return None


def problems(markdown: Path, repo: Repository) -> Iterator[str]:
    """One message per citation in the file that names a missing file or definition."""
    last: str | None = None  # the file cited last in this paragraph, for a short ::name
    for number, line in enumerate(markdown.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("|"):
            last = None
        for code in CODE.findall(line):
            if (found := CITATION.fullmatch(code)) is None:
                continue
            if found["path"] is not None:
                last = repo.resolve(found["path"])
            if (message := unresolved(found, last, repo)) is not None:
                yield f"{markdown}:{number}: `{code}`: {message}"


def unresolved(found: re.Match[str], file: str | None, repo: Repository) -> str | None:
    """Why a citation does not resolve in the file it names or follows, or None if it does."""
    path, names = found["path"], found["names"].split("::")[1:]
    if not names:  # a bare path: no citation of its own
        return None
    if file is None:
        if path is not None:
            return f"no tracked file, or more than one, is {path}"
        return "no cited file before it in the paragraph"
    gone = repo.missing(file, [re.sub(r"\[.*", "", name) for name in names])
    return None if gone is None else f"{file} defines no {gone}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="Markdown files (default: tracked)")
    args = parser.parse_args(argv)
    named = [path.resolve() for path in args.files]
    root = Path(git("rev-parse", "--show-toplevel").strip())
    os.chdir(root)
    files = [path.relative_to(root) if path.is_relative_to(root) else path for path in named]
    files = files or [Path(name) for name in tracked("*.md") if not name.startswith(HISTORY)]
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
