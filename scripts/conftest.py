# AI-ASSISTED: a throwaway git repository for the pull-request check tests.
"""The ``pr_repo`` fixture of the tests of scripts/check_pr.py, scripts/review_budget.py and
scripts/check_citations.py: a throwaway repository, also the working folder."""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRAILER = "AI-Assisted: Claude Code (test)"


class Repo:
    """A git repository in a temporary folder, isolated from the user's git configuration."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],  # noqa: S607
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def commit(self, files: Mapping[str, str | bytes | None], message: str = "") -> str:
        """Write each file (None deletes it), commit everything and return the commit."""
        for name, text in files.items():
            if text is None:
                self.git("rm", "-q", name)
                continue
            path = self.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(text, bytes):
                path.write_bytes(text)
            else:
                path.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message or f"Change files\n\n{TRAILER}")
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def pr_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A repository with the real .gitattributes on main, and the working folder set to it."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@noreply.invalid")
    monkeypatch.chdir(tmp_path)
    repo = Repo(tmp_path)
    repo.git("init", "-q", "-b", "main")
    shutil.copy(ROOT / ".gitattributes", tmp_path / ".gitattributes")
    repo.commit({})
    return repo
