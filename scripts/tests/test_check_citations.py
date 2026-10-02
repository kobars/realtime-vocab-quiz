# AI-ASSISTED: tests for the check that Markdown test citations name existing tests.
import check_citations
import pytest
from conftest import Repo

TESTS = """\
import pytest


def test_kept() -> None: ...


async def test_async() -> None: ...


class TestGroup:
    def test_method(self) -> None: ...


def helper() -> None:
    def inner() -> None: ...


TestMachine = object
"""


def run(pr_repo: Repo, markdown: str) -> int:
    pr_repo.commit({"api/tests/unit/test_x.py": TESTS, "docs/spec/x.md": markdown})
    return check_citations.main([])


def test_existing_citations_pass(pr_repo: Repo) -> None:
    line = (
        "`api/tests/unit/test_x.py::test_kept`, `::test_async`, `unit/test_x.py::TestGroup`,"
        " `api/tests/unit/test_x.py::TestGroup::test_method`, `::TestMachine` and"
        " `api/tests/unit/test_x.py::test_kept[redis]`; `cd api && pytest` is no citation\n"
    )
    assert run(pr_repo, line) == 0


@pytest.mark.parametrize(
    ("citation", "message"),
    [
        ("`api/tests/unit/test_x.py::test_gone`", "api/tests/unit/test_x.py defines no test_gone"),
        (
            "`api/tests/unit/test_y.py::test_kept`",
            "no tracked file, or more than one, is api/tests/unit/test_y.py",
        ),
        (
            "`api/tests/unit/test_x.py::TestGroup::test_gone`",
            "api/tests/unit/test_x.py defines no TestGroup::test_gone",
        ),
        (
            "`api/tests/unit/test_x.py::TestGroup::test_kept`",
            "api/tests/unit/test_x.py defines no TestGroup::test_kept",
        ),
        ("`api/tests/unit/test_x.py::inner`", "api/tests/unit/test_x.py defines no inner"),
        ("`::test_kept`", "no cited file before it in the paragraph"),
    ],
)
def test_a_missing_file_or_test_fails(
    pr_repo: Repo, capsys: pytest.CaptureFixture[str], citation: str, message: str
) -> None:
    assert run(pr_repo, f"Proved by {citation}.\n") == 1
    assert f"docs/spec/x.md:1: {citation}: {message}" in capsys.readouterr().err


def test_a_short_citation_names_a_test_of_the_file_cited_before_it(
    pr_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(pr_repo, "`api/tests/unit/test_x.py::test_kept` and `::test_gone`\n") == 1
    assert "`::test_gone`: api/tests/unit/test_x.py defines no test_gone" in capsys.readouterr().err


@pytest.mark.parametrize(
    "markdown",
    [
        "`api/tests/unit/test_x.py::test_kept` and\n`::test_async` share a wrapped paragraph\n",
        "`api/tests/unit/test_x.py` (`::test_kept`, `::TestGroup::test_method`)\n",
    ],
)
def test_a_short_citation_follows_a_file_cited_earlier_in_the_paragraph(
    pr_repo: Repo, markdown: str
) -> None:
    assert run(pr_repo, markdown) == 0


@pytest.mark.parametrize(
    "markdown",
    [
        "`api/tests/unit/test_x.py::test_kept`\n\n`::test_async`\n",
        "| `api/tests/unit/test_x.py::test_kept` |\n| `::test_async` |\n",
    ],
)
def test_a_short_citation_never_reaches_into_another_paragraph_or_table_row(
    pr_repo: Repo, capsys: pytest.CaptureFixture[str], markdown: str
) -> None:
    assert run(pr_repo, markdown) == 1
    assert "`::test_async`: no cited file before it in the paragraph" in capsys.readouterr().err


def test_a_run_from_a_subfolder_checks_the_whole_repository(
    pr_repo: Repo, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pr_repo.commit({"api/tests/unit/test_x.py": TESTS, "docs/spec/x.md": "`unit/test_x.py::no`\n"})
    monkeypatch.chdir(pr_repo.path / "api")
    assert check_citations.main([]) == 1
    assert "docs/spec/x.md:1:" in capsys.readouterr().err


def test_a_tracked_file_deleted_from_the_work_tree_is_reported_not_raised(
    pr_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    pr_repo.commit({"api/tests/unit/test_x.py": TESTS, "docs/spec/x.md": "`unit/test_x.py::a`\n"})
    (pr_repo.path / "api/tests/unit/test_x.py").unlink()
    assert check_citations.main([]) == 1
    assert "no tracked file, or more than one, is unit/test_x.py" in capsys.readouterr().err


def test_the_ai_log_history_is_not_checked(pr_repo: Repo) -> None:
    pr_repo.commit({"docs/ai-log/PR-1.md": "`api/tests/unit/test_x.py::test_removed_since`\n"})
    assert run(pr_repo, "`api/tests/unit/test_x.py::test_kept`\n") == 0
