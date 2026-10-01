# AI-ASSISTED: under the suite's own pytest config a hung test fails as Timeout and the run goes on.
import pytest

pytest_plugins = ["pytester"]

HUNG_AND_HEALTHY = """
import time

def test_hangs():
    time.sleep(30)

def test_runs_after_the_hang():
    pass
"""


def test_a_hung_test_fails_as_timeout_and_the_next_test_still_runs(
    pytestconfig: pytest.Config, pytester: pytest.Pytester
) -> None:
    assert pytestconfig.getini("timeout"), "the suite sets no per-test timeout"
    tests = pytester.makepyfile(HUNG_AND_HEALTHY)

    result = pytester.runpytest_subprocess(
        "-c", str(pytestconfig.inipath), "-o", "timeout=1", "-p", "no:cacheprovider", str(tests)
    )

    result.assert_outcomes(failed=1, passed=1)
    result.stdout.fnmatch_lines(["*Failed: Timeout*", "*FAILED*test_hangs*"])
