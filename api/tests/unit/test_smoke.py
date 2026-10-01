# AI-ASSISTED: smoke test for the pytest, pytest-asyncio and Hypothesis wiring.
import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import quiz


def test_package_imports() -> None:
    assert quiz.__doc__


def test_folder_sets_the_marker(request: pytest.FixtureRequest) -> None:
    assert request.node.get_closest_marker("unit") is not None


async def test_async_tests_run_without_a_marker() -> None:
    assert await asyncio.sleep(0, result=42) == 42


@given(st.integers())
def test_hypothesis_runs_with_a_registered_profile(value: int) -> None:
    assert settings().max_examples in {50, 500}
    assert -value == 0 - value
