# AI-ASSISTED: tests for the JUnit skip check that guards the acceptance runs.
from pathlib import Path

import pytest

import check_junit_skips

EXACT_TIME = "exact-time check: runs on the memory store with the injected clock"


def report(tmp_path: Path, *skips: str, passed: int = 11) -> Path:
    """A pytest-style JUnit report: ``passed`` passing cases and one skipped case per message."""
    cases = [f'<testcase classname="t" name="ok{n}"/>' for n in range(passed)]
    cases += [
        f'<testcase classname="t" name="skip{n}"><skipped message="{message}"/></testcase>'
        for n, message in enumerate(skips)
    ]
    path = tmp_path / "report.xml"
    path.write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>")
    return path


def test_a_run_without_skips_passes(tmp_path: Path) -> None:
    assert check_junit_skips.main([str(report(tmp_path))]) == 0


def test_one_unexpected_skip_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = report(tmp_path, "quiz.main:create_app does not exist yet")
    assert check_junit_skips.main([str(path)]) == 1
    assert "t::skip0: quiz.main:create_app does not exist yet" in capsys.readouterr().err


def test_the_expected_skips_pass(tmp_path: Path) -> None:
    path = report(tmp_path, EXACT_TIME, EXACT_TIME)
    assert check_junit_skips.main([str(path), "--expect", "2", "--reason", "exact-time"]) == 0


@pytest.mark.parametrize(
    "skips",
    [(EXACT_TIME,), (EXACT_TIME, EXACT_TIME, EXACT_TIME), (EXACT_TIME, "needs REDIS_URL")],
    ids=["too-few", "too-many", "other-reason"],
)
def test_skips_other_than_the_expected_ones_fail(tmp_path: Path, skips: tuple[str, ...]) -> None:
    path = report(tmp_path, *skips)
    assert check_junit_skips.main([str(path), "--expect", "2", "--reason", "exact-time"]) == 1


def test_a_report_without_tests_fails(tmp_path: Path) -> None:
    assert check_junit_skips.main([str(report(tmp_path, passed=0))]) == 1
