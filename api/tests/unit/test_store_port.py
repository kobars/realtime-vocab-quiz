# AI-ASSISTED: the store port surface that docs/spec/redis.md §3 needs, and the QUIZ_ENDED end seq.
import inspect
import re
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

from quiz.domain import errors
from quiz.domain.errors import DomainError, ErrorCode
from quiz.ports.store import Ranks, Renewed, Store

PROTOCOL = Path(__file__).resolve().parents[3] / "docs" / "spec" / "protocol.md"


def params(method: object) -> list[str]:
    return list(inspect.signature(method).parameters)  # type: ignore[arg-type]


def test_quiz_ended_refusal_carries_end_seq() -> None:
    assert DomainError(ErrorCode.QUIZ_ENDED, "ended").end_seq is None  # not announced yet
    assert DomainError(ErrorCode.QUIZ_ENDED, "ended", end_seq=7).end_seq == 7


def test_port_renews_presence_and_marks_dirty() -> None:
    assert params(Store.renew_presence) == ["self", "quiz_id", "stale_ms", "pairs"]
    assert get_type_hints(Store.renew_presence)["return"] is Renewed
    assert [f.name for f in fields(Renewed)] == ["status", "removed"]
    assert params(Store.mark_dirty) == ["self", "quiz_id"]
    assert get_type_hints(Store.mark_dirty)["return"] is type(None)


def test_port_reads_many_ranks_at_one_seq() -> None:
    assert not hasattr(Store, "rank_of")
    assert params(Store.ranks_of) == ["self", "quiz_id", "user_ids"]
    assert get_type_hints(Store.ranks_of)["return"] is Ranks
    assert [f.name for f in fields(Ranks)] == ["at_seq", "status", "player_count", "rows"]


def test_errors_marker_cites_the_errors_section() -> None:
    marker = Path(errors.__file__).read_text(encoding="utf-8").splitlines()[0]
    found = re.search(r"protocol\.md §(\d+)", marker)
    assert found is not None
    assert f"\n## {found[1]}. Errors and close codes\n" in PROTOCOL.read_text(encoding="utf-8")
