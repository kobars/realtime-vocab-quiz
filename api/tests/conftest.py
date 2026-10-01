# AI-ASSISTED: shared pytest setup: Hypothesis profiles and markers taken from the test folder.
import os
from pathlib import Path

import pytest
from hypothesis import settings

settings.register_profile("dev", max_examples=50)
settings.register_profile("ci", max_examples=500, deadline=None, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

_TESTS = Path(__file__).parent
_FOLDER_MARKERS = frozenset({"unit", "property", "contract", "integration", "acceptance"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test by its folder, so `-m "not integration"` needs no per-test markers."""
    for item in items:
        if item.path.is_relative_to(_TESTS):
            folder = item.path.relative_to(_TESTS).parts[0]
            if folder in _FOLDER_MARKERS:
                item.add_marker(folder)
