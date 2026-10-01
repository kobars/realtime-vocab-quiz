# AI-ASSISTED: tests for the internal-content guard (patterns, files, commits and stdin modes).
"""Tests for scripts/check_internal.py.

Samples that must be caught are assembled from parts with ``j()``, so this file
passes the guard's own scan of the tracked files.
"""

import io
import os
import subprocess
from pathlib import Path

import pytest

import check_internal


def j(*parts: str) -> str:
    return "".join(parts)


CAUGHT = [
    ("task id", j("see K", "-045 for details")),
    ("decision id", j("as decided in Q", "7")),
    ("decision id", j("Q", "21 applies")),
    ("review id", j("fixed after R", "-3")),
    ("review id", j("R", "-30")),
    ("internal word", j("move it on the kan", "ban board")),
    ("internal word", j("the Recr", "uiter asked")),
    ("internal word", j("before the inter", "view")),
    ("internal word", j("the can", "on says so")),
    ("course phrase", j("see the course ", "module")),
    ("course phrase", j("course ", "can", "on")),
    ("docs product", j("written in Claude ", "Docs")),
    ("artifact link", j("https://claude", ".ai/code/artifact/abc")),
    ("home path", j("/", "Users/someone/project")),
    ("home path", j("/", "home/someone/project")),
    ("actor name", j("lead", "/claude-opus")),
    ("email address", j("someone", "@", "example.org")),
]

CLEAN = [
    "q1",
    "Q22",
    "vocab42-01",
    "docs/ai-log/PR-12.md",
    "docs/ai-log/design-phase.md",
    "feat/redis-adapter",
    "AI-Assisted: Claude Code (claude-opus-5-5)",
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "12345+someone@users.noreply.github.com",
    "a canonical form",
    "covers AC-4, F-3 and V-11",
    "K-12 and K-1234 are not task IDs",
    "PR-12 and XR-1 are not review IDs",
    "@vue/test-utils@2.5.1",
]


@pytest.mark.parametrize(("rule", "text"), CAUGHT)
def test_each_pattern_catches_its_sample(rule: str, text: str) -> None:
    assert [finding.rule for finding in check_internal.scan_text(text)] == [rule]


@pytest.mark.parametrize("text", CLEAN)
def test_clean_text_passes(text: str) -> None:
    assert check_internal.scan_text(text) == []


def test_findings_carry_line_numbers() -> None:
    findings = check_internal.scan_text(j("clean\n\nsee K", "-101\n"))
    assert [(f.line, f.match) for f in findings] == [(3, j("K", "-101"))]


def test_stdin_mode(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(j("Title\n\nBody mentions Q", "3\n")))
    assert check_internal.main(["--stdin"]) == 1
    assert "stdin:3: decision id" in capsys.readouterr().out

    monkeypatch.setattr("sys.stdin", io.StringIO("Add the scoring script\n"))
    assert check_internal.main(["--stdin"]) == 0


def test_file_mode_scans_contents_and_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    clean = Path("clean.md")
    clean.write_text("nothing to see\n")
    dirty_name = Path(j("notes-K", "-077.md"))
    dirty_name.write_text("nothing to see\n")
    binary = Path("image.png")
    binary.write_bytes(b"\x89PNG\x00" + j("/", "Users/").encode())

    assert check_internal.main([str(clean), str(binary)]) == 0
    assert check_internal.main([str(dirty_name)]) == 1


HOSTILE_GIT_CONFIG = "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = false\n"


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    """Run git isolated from the user's and the system's git configuration."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@noreply.invalid", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            **(env or {}),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )


def test_git_helper_ignores_the_global_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = tmp_path / "gitconfig"
    hostile.write_text(HOSTILE_GIT_CONFIG)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "Add the store port")


def test_commits_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Add the store port")
    monkeypatch.chdir(tmp_path)
    assert check_internal.main(["--commits", "HEAD"]) == 0

    git(tmp_path, "commit", "-q", "--allow-empty", "-m", j("Fix it\n\nSee R", "-12"))
    assert check_internal.main(["--commits", "HEAD~1..HEAD"]) == 1


@pytest.mark.parametrize("role", ["AUTHOR", "COMMITTER"])
def test_commits_mode_scans_author_and_committer_emails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role: str,
) -> None:
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    noreply = {f"GIT_{role}_EMAIL": "12345+someone@users.noreply.github.com"}
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Add the store port", env=noreply)
    assert check_internal.main(["--commits", "HEAD"]) == 0

    personal = {f"GIT_{role}_EMAIL": j("someone", "@", "example.org")}
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Add the tick", env=personal)
    assert check_internal.main(["--commits", "HEAD~1..HEAD"]) == 1
    assert f"{role.lower()} email: email address" in capsys.readouterr().out


def test_empty_commit_range_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Add the store port")
    monkeypatch.chdir(tmp_path)
    assert check_internal.main(["--commits", ""]) == 2
    assert "empty" in capsys.readouterr().err


def test_bad_commit_range_is_an_error_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    assert check_internal.main(["--commits", "no-such-ref..HEAD"]) == 2
    assert "git failed" in capsys.readouterr().err


def test_symlink_target_is_scanned_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    Path("link").symlink_to(j("/", "Users/someone/notes.md"))
    git(tmp_path, "add", "link")
    git(tmp_path, "commit", "-q", "-m", "Add a link")

    assert check_internal.main([]) == 1
    assert "link: symlink target: home path" in capsys.readouterr().out
    assert check_internal.main(["link"]) == 1

    Path("dirty.md").write_text(j("see K", "-045\n"))
    Path("relative-link").symlink_to("dirty.md")
    assert check_internal.main(["relative-link"]) == 0


def test_absolute_paths_are_named_relative_to_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "home" / "someone" / "repo"
    (repo / "docs").mkdir(parents=True)
    git(repo, "init", "-q")
    readme = repo / "docs" / "README.md"
    readme.write_text("nothing to see\n")
    monkeypatch.chdir(repo / "docs")
    assert check_internal.main([str(readme)]) == 0
    assert check_internal.main(["README.md"]) == 0
