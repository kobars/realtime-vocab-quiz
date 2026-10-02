# AI-ASSISTED: tests for the display name rule on the cases shared with the join form's tests.
import json
from pathlib import Path

import pytest

from quiz.domain.names import display_name

CASES = json.loads(
    (Path(__file__).resolve().parents[3] / "docs" / "spec" / "display-names.json").read_text()
)


@pytest.mark.parametrize("case", CASES["refused"], ids=lambda case: case["case"])
def test_refused(case: dict[str, str]) -> None:
    assert display_name(case["name"]) is None


@pytest.mark.parametrize("case", CASES["accepted"], ids=lambda case: case["case"])
def test_accepted(case: dict[str, str]) -> None:
    assert display_name(case["name"]) == case["stored"]
