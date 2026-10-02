# AI-ASSISTED: tests for the pull-request guards, one throwaway repository per failure.
"""Tests for scripts/check_pr.py."""

import subprocess

import pytest
from conftest import TRAILER, Repo

import check_pr

PR = 7
ENTRY = {f"docs/ai-log/PR-{PR}.md": "## PR-7 — Test\n"}


def _check(base: str, capsys: pytest.CaptureFixture[str], *labels: str) -> tuple[int, str]:
    status = check_pr.main(["--base", base, "--head", "HEAD", "--pr", str(PR), "--labels", *labels])
    return status, capsys.readouterr().out


def _dependabot_commit(repo: Repo, files: dict[str, str], message: str) -> str:
    """Commit as Dependabot does: its author, no trailer."""
    repo.commit(files, message)
    repo.git(
        "commit", "-q", "--amend", "--no-edit", f"--author=dependabot[bot] <{check_pr.DEPENDABOT}>"
    )
    return repo.git("rev-parse", "--short", "HEAD").strip()


@pytest.fixture
def base(pr_repo: Repo) -> str:
    pr_repo.commit(
        {
            "api/tests/acceptance/test_join.py": "def test_join(): ...\n",
            "api/tests/conftest.py": "",
            "api/pyproject.toml": '[tool.pytest.ini_options]\naddopts = ["-ra"]\n',
        }
    )
    return pr_repo.git("rev-parse", "HEAD").strip()


def test_a_clean_pr_passes(pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]) -> None:
    pr_repo.commit({"app.py": "x = 1\n", **ENTRY})
    assert _check(base, capsys) == (
        0,
        "PR guards passed: 2 changed lines, generated files not counted\n",
    )


@pytest.mark.parametrize(
    "files",
    [
        {"api/tests/acceptance/test_join.py": "def test_join(): assert True\n"},
        {"api/tests/acceptance/test_join.py": None},
        {"api/tests/acceptance/test_new.py": "def test_new(): ...\n"},
        {"api/tests/conftest.py": "import pytest\n"},
        {"api/pyproject.toml": '[tool.pytest.ini_options]\naddopts = ["-q"]\n'},
    ],
)
def test_frozen_paths_need_the_acceptance_label(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str], files: dict[str, str | None]
) -> None:
    pr_repo.commit({**files, **ENTRY})
    status, out = _check(base, capsys)
    assert status == 1
    assert f"frozen paths changed without the {check_pr.ACCEPTANCE_LABEL} label" in out
    assert _check(base, capsys, check_pr.ACCEPTANCE_LABEL)[0] == 0


def test_a_moved_acceptance_test_is_a_frozen_change(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.git("mv", "api/tests/acceptance/test_join.py", "api/tests/test_join.py")
    pr_repo.commit(ENTRY)
    assert "api/tests/acceptance/test_join.py" in _check(base, capsys)[1]


def test_other_pyproject_tables_are_not_frozen(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = '[tool.pytest.ini_options]\naddopts = ["-ra"]\n\n[tool.ruff]\nline-length = 99\n'
    pr_repo.commit({"api/pyproject.toml": pyproject, **ENTRY})
    assert _check(base, capsys)[0] == 0


def test_size_limit_counts_changed_lines_without_generated_files(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = check_pr.MAX_CHANGED_LINES - 1  # the AI-LOG entry adds the last line
    big = "x\n" * 1000
    pr_repo.commit(
        {
            "app.py": "x\n" * lines,
            "api/uv.lock": big,
            "web/packages/clay/src/components/a.vue": big,
            **ENTRY,
        }
    )
    assert _check(base, capsys)[0] == 0

    pr_repo.commit({"app.py": "x\n" * (lines + 1)})
    status, out = _check(base, capsys)
    assert status == 1
    assert f"{check_pr.MAX_CHANGED_LINES + 1} changed lines, over" in out
    assert _check(base, capsys, check_pr.SIZE_LABEL)[0] == 0


@pytest.mark.parametrize(
    ("message", "problem"),
    [
        ("Add the tick", "has no AI-Assisted: trailer"),
        (f"fixup! Add the tick\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"squash! Add the tick\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"amend! Add the tick\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"WIP tick\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"WIP: tick\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"WIP\n\n{TRAILER}", "is a fixup, squash, amend or WIP commit"),
        (f"{'a' * (check_pr.MAX_SUBJECT + 1)}\n\n{TRAILER}", "has a subject over"),
    ],
)
def test_each_commit_needs_the_trailer_and_a_plain_short_subject(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str], message: str, problem: str
) -> None:
    pr_repo.commit(ENTRY)
    pr_repo.commit({"app.py": "x = 1\n"}, message)
    status, out = _check(base, capsys)
    assert status == 1
    assert problem in out


def test_a_subject_that_is_not_utf8_is_reported(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.commit(ENTRY)
    # git commit turns a Latin-1 message into UTF-8, so write the commit object directly.
    head = pr_repo.git("cat-file", "commit", "HEAD").split("\n\n")[0]
    raw = f"{head}\n\nWIP caf\udce9\n\n{TRAILER}\n".encode(errors="surrogateescape")
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"],  # noqa: S607
        input=raw,
        capture_output=True,
        check=True,
    ).stdout.decode()
    pr_repo.git("reset", "-q", sha.strip())
    status, out = _check(base, capsys)
    assert status == 1
    assert out.endswith("is a fixup, squash, amend or WIP commit: WIP caf\ufffd\n")


def test_a_subject_that_starts_with_a_longer_word_than_wip_passes(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.commit(ENTRY, f"WIPE stale sessions on shutdown\n\n{TRAILER}")
    assert _check(base, capsys)[0] == 0


def test_a_subject_at_the_length_limit_and_a_merge_commit_pass(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.git("checkout", "-q", "-b", "side")
    pr_repo.commit({"side.py": "y = 1\n"}, f"{'a' * check_pr.MAX_SUBJECT}\n\n{TRAILER}")
    pr_repo.git("checkout", "-q", "main")
    pr_repo.commit(ENTRY)
    pr_repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
    assert _check(base, capsys)[0] == 0


def test_the_ai_log_entry_must_exist(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.commit({"app.py": "x = 1\n"})
    status, out = _check(base, capsys)
    assert status == 1
    assert f"::error title=PR guards::the AI-LOG entry docs/ai-log/PR-{PR}.md is missing" in out


def test_a_dependabot_pr_needs_no_trailer_and_no_ai_log_entry(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _dependabot_commit(pr_repo, {"api/uv.lock": "x\n"}, "Bump uv-build in /api")
    assert _check(base, capsys) == (
        0,
        "PR guards passed: 0 changed lines, generated files not counted\n",
    )


def test_a_commit_pushed_onto_a_dependabot_pr_needs_the_trailer_and_the_entry(
    pr_repo: Repo, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    bump = _dependabot_commit(pr_repo, {"compose.yaml": "redis\n"}, "Bump redis")
    follow = pr_repo.commit({"ci.yml": "redis\n"}, "Follow the Redis bump")
    status, out = _check(base, capsys)
    assert status == 1
    assert out.count("has no AI-Assisted: trailer") == 1
    assert f"commit {follow[:7]}" in out
    assert f"commit {bump} " not in out
    assert f"the AI-LOG entry docs/ai-log/PR-{PR}.md is missing" in out


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (({"app.py": "x\n" * (check_pr.MAX_CHANGED_LINES + 1)}, "Bump"), "changed lines, over"),
        (({"api/tests/conftest.py": "import pytest\n"}, "Bump"), "frozen paths changed"),
        (({"app.py": "x = 1\n"}, "a" * (check_pr.MAX_SUBJECT + 1)), "has a subject over"),
    ],
)
def test_a_dependabot_pr_still_meets_the_other_rules(
    pr_repo: Repo,
    base: str,
    capsys: pytest.CaptureFixture[str],
    change: tuple[dict[str, str], str],
    problem: str,
) -> None:
    _dependabot_commit(pr_repo, *change)
    status, out = _check(base, capsys)
    assert status == 1
    assert problem in out
