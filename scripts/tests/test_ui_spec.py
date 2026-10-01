# AI-ASSISTED: checks that the UI spec's connection chart has an edge for every table change.
"""The connection chart (ui.md §4.1) and the message table (§4.3) must agree.

Each "Connection change" cell of the table names transitions as
``source → target``. A change written without a source state applies from
every connected state. Every such transition must be an edge of the chart.
"""

import re
from pathlib import Path

UI_SPEC = Path(__file__).resolve().parents[2] / "docs" / "spec" / "ui.md"
CONNECTED = ("joining", "resyncing", "live")
STATES = {
    "idle",
    "connecting",
    "joining",
    "resyncing",
    "live",
    "reconnecting",
    "blocked",
    "closed",
}


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n#", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def chart_edges(text: str) -> set[tuple[str, str]]:
    chart = section(text, "### 4.1 Connection")
    edges = re.findall(r"^\s*(\w+) --> (\w+)", chart, flags=re.MULTILINE)
    return {(a, b) for a, b in edges}


def table_changes(text: str) -> list[tuple[str, str, str]]:
    """Return (input, source, target) for every transition in the §4.3 table."""
    table = section(text, "### 4.3 Every message")
    changes: list[tuple[str, str, str]] = []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or "→" not in cells[2]:
            continue
        for part in cells[2].split(";"):
            if "→" not in part:
                continue
            before, after = part.split("→", 1)
            targets = [s for s in re.findall(r"`(\w+)`", after) if s in STATES]
            assert targets, f"no target state in {cells[0]!r}: {part!r}"
            sources = [s for s in re.findall(r"`(\w+)`", before) if s in STATES]
            changes.extend((cells[0], s, targets[0]) for s in sources or CONNECTED)
    return changes


def test_table_has_transitions() -> None:
    assert len(table_changes(UI_SPEC.read_text(encoding="utf-8"))) > 20


def test_every_table_transition_is_a_chart_edge() -> None:
    text = UI_SPEC.read_text(encoding="utf-8")
    edges = chart_edges(text)
    missing = sorted(
        f"{source} → {target} ({row})"
        for row, source, target in table_changes(text)
        if (source, target) not in edges
    )
    assert not missing, "chart lacks edges: " + "; ".join(missing)


def test_join_after_the_end_leaves_joining() -> None:
    edges = chart_edges(UI_SPEC.read_text(encoding="utf-8"))
    assert ("joining", "live") in edges
    assert ("joining", "idle") in edges
