# AI-ASSISTED: checks that the protocol spec covers every atSeq unicast and every upgrade refusal.
"""The protocol spec (docs/spec/protocol.md) must agree with the contracts.

- Every server message with an ``atSeq`` field has a client rule in the §3
  table, so the client and the bots treat ``atSeq`` the same way.
- Every §7 error row that names an HTTP status at the upgrade says the
  browser sees it as close 1006, since no ``error`` frame exists for it.
"""

import re
import typing
from pathlib import Path

from quiz.contracts.messages import ServerMessage

PROTOCOL_SPEC = Path(__file__).resolve().parents[2] / "docs" / "spec" / "protocol.md"


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def at_seq_types() -> set[str]:
    union = typing.get_args(ServerMessage.__value__)[0]
    return {
        model.model_fields["type"].default
        for model in typing.get_args(union)
        if "atSeq" in model.model_fields
    }


def test_every_at_seq_message_has_a_client_rule() -> None:
    table = section(PROTOCOL_SPEC.read_text(encoding="utf-8"), "## 3. Sequence numbers")
    incoming = " ".join(row[0] for row in table_rows(table))
    named = set(re.findall(r"`(\w+)`", incoming))
    missing = at_seq_types() - named
    assert not missing, f"no §3 client rule for atSeq of {sorted(missing)}"


def test_upgrade_refusals_are_seen_as_1006() -> None:
    table = section(PROTOCOL_SPEC.read_text(encoding="utf-8"), "## 7. Errors")
    upgrade_rows = [row for row in table_rows(table) if re.search(r"HTTP \d{3}", row[1])]
    assert len(upgrade_rows) >= 4
    for code, when, action in (row[:3] for row in upgrade_rows):
        assert "1006" in when + action, f"{code}: an upgrade refusal must read as close 1006"
