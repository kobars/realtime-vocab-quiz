# AI-ASSISTED: checks that the AI-drafted ADRs in docs/DECISIONS.md sit inside AI-ASSISTED blocks.
"""The AI-drafted ADRs in docs/DECISIONS.md carry the AI-ASSISTED marker.

AGENTS.md asks for a marker in every file AI wrote or changed. Every line of
each listed ADR section below its heading must sit inside an ``AI-ASSISTED-BEGIN`` …
``AI-ASSISTED-END`` block, and the blocks must be balanced and never nested.
"""

from pathlib import Path

import pytest

DECISIONS = Path(__file__).resolve().parents[2] / "docs" / "DECISIONS.md"
BEGIN = "<!-- AI-ASSISTED-BEGIN:"
END = "<!-- AI-ASSISTED-END -->"


def _marked_lines() -> list[tuple[str, bool]]:
    """Return each non-marker line with whether it lies inside an AI-ASSISTED block."""
    inside = False
    marked = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith(BEGIN):
            assert not inside, "nested AI-ASSISTED-BEGIN"
            inside = True
        elif line.strip() == END:
            assert inside, "AI-ASSISTED-END without a BEGIN"
            inside = False
        else:
            marked.append((line, inside))
    assert not inside, "AI-ASSISTED-BEGIN without an END"
    return marked


@pytest.mark.parametrize("adr", ["ADR-001", "ADR-009"])
def test_ai_drafted_adr_is_inside_a_marker_block(adr: str) -> None:
    lines = _marked_lines()
    start = next(i for i, (line, _) in enumerate(lines) if line.startswith(f"## {adr} "))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i][0].startswith("## ")),
        len(lines),
    )
    unmarked = [line for line, inside in lines[start + 1 : end] if line.strip() and not inside]
    assert unmarked == []
