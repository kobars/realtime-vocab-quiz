# AI-ASSISTED: tests for the review budget: thresholds, exclusions, renames, deletions, output.
"""Tests for scripts/review_budget.py, on throwaway repositories with a stubbed token counter."""

from pathlib import Path

import pytest
from conftest import Repo

import review_budget

LIMITS = review_budget.budget()


def _run(monkeypatch: pytest.MonkeyPatch, base: str, tokens_per_file: int = 1) -> int:
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return review_budget.main(count=lambda _text: tokens_per_file)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (LIMITS["info"] - 1, (None, 0)),
        (LIMITS["info"], ("::notice ", 0)),
        (LIMITS["warning"], ("::warning ", 0)),
        (LIMITS["limit"], (f"::error title=Review budget::{review_budget.EXCEEDED}", 1)),
    ],
)
def test_each_threshold_starts_its_level(
    pr_repo: Repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tokens: int,
    expected: tuple[str | None, int],
) -> None:
    annotation, status = expected
    base = pr_repo.git("rev-parse", "HEAD").strip()
    pr_repo.commit({"app.py": "print('hi')\n"})
    assert _run(monkeypatch, base, tokens) == status
    out = capsys.readouterr().out.splitlines()
    assert (
        out[0]
        == f"review input: {tokens:,} tokens in 1 files ({review_budget.level(tokens, LIMITS)})"
    )
    if annotation is None:
        assert len(out) == 1
    else:
        assert out[1].startswith(annotation)


def test_lock_and_generated_files_are_left_out(pr_repo: Repo) -> None:
    base = pr_repo.git("rev-parse", "HEAD").strip()
    pr_repo.commit(
        {
            "app.py": "x = 1\n",
            "api/uv.lock": "lock\n",
            "web/pnpm-lock.yaml": "lock\n",
            "web/src/protocol/types.generated.ts": "export type A = 1\n",
            "contracts/schema/protocol.json": "{}\n",
            "web/src/components/ui/button/Button.vue": "<template />\n",
        }
    )
    assert list(review_budget.review_input(base, "HEAD")) == ["app.py"]


def test_a_renamed_file_counts_its_diff_and_its_new_contents(pr_repo: Repo) -> None:
    pr_repo.commit({"old.py": "".join(f"line {i}\n" for i in range(20))})
    base = pr_repo.git("rev-parse", "HEAD").strip()
    pr_repo.git("mv", "old.py", "new.py")
    pr_repo.commit({"new.py": "".join(f"line {i}\n" for i in range(21))})
    (text,) = review_budget.review_input(base, "HEAD").values()
    assert list(review_budget.review_input(base, "HEAD")) == ["new.py"]
    assert "rename from old.py\nrename to new.py\n" in text
    assert "+line 20\n" in text
    assert text.endswith("line 19\nline 20\n")


def test_a_deleted_file_counts_only_its_diff(pr_repo: Repo) -> None:
    pr_repo.commit({"gone.py": "a = 1\n"})
    base = pr_repo.git("rev-parse", "HEAD").strip()
    pr_repo.commit({"gone.py": None})
    texts = review_budget.review_input(base, "HEAD")
    assert texts == {"gone.py": pr_repo.git("diff", base, "HEAD")}


@pytest.mark.usefixtures("pr_repo")
def test_an_empty_diff_is_zero_tokens_and_no_annotation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "HEAD") == 0
    assert capsys.readouterr().out == "review input: 0 tokens in 0 files (ok)\n"


def test_the_step_summary_has_the_total_and_the_largest_files(
    pr_repo: Repo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = pr_repo.git("rev-parse", "HEAD").strip()
    pr_repo.commit({"a.py": "a\n", "b.py": "bb\n"})
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert review_budget.main(count=len) == 0
    rows = summary.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "### Review budget"
    total = len(pr_repo.git("diff", base, "HEAD")) + len("a\nbb\n")
    assert rows[4] == f"| **Total (2 files, ok)** | **{total:,}** |"
    assert [row.split("`")[1] for row in rows[5:]] == ["b.py", "a.py"]
