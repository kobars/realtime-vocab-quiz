# AI-ASSISTED: a repair after a resubscribe builds and encodes the shared standings once per quiz.
from collections.abc import Sequence
from typing import Any, cast
from unittest.mock import Mock

import pytest

from quiz.app.service import QuizService
from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.fanout.broadcast import Relay, Sockets
from quiz.fanout.tick import Ticker
from quiz.ports.store import FeedStore, Limits, Place, Ranks, Row, Snapshot, Store

SEQ, PLAYERS, TOP_N = 7, 300, 50
ROWS = tuple(Row(rank, f"u{rank}", f"U{rank}", 1_000 - rank) for rank in range(1, TOP_N + 1))
OUTSIDER = "watcher"  # a local socket of a user who is not a player


def place(user_id: str) -> Place | None:
    rank = None if user_id == OUTSIDER else int(user_id[1:])
    return None if rank is None else Place(rank, 1_000 - rank)


class RepairStore:
    """Quiz Q at ``SEQ`` with ``PLAYERS`` players, so its standings hold the top ``TOP_N``."""

    limits = Limits(tick_ms=10)

    async def ranks_of(self, _quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        return Ranks(SEQ, "open", PLAYERS, {user_id: place(user_id) for user_id in user_ids})

    async def snapshot(self, _quiz_id: str, _user_id: str | None) -> Snapshot:
        return Snapshot(SEQ, "open", PLAYERS, PLAYERS, ROWS, None)


@pytest.fixture
def entries_built(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The user id of each wire entry built from a standings row."""
    built: list[str] = []
    entry = Row.entry

    def counted(row: Row) -> m.Entry:
        built.append(row.user_id)
        return entry(row)

    monkeypatch.setattr(Row, "entry", counted)
    return built


def expected(user_id: str, entries: list[m.Entry]) -> list[bytes]:
    """What a resync gives the user at ``SEQ``: the snapshot, then ``rank_update`` outside it."""
    own = place(user_id)
    you = None if own is None else m.You(rank=own.rank, score=own.score)
    snap = m.Snapshot(
        atSeq=SEQ, status="open", playerCount=PLAYERS, onlineCount=PLAYERS, entries=entries, you=you
    )
    if you is None or you.rank <= TOP_N:
        return [encode(snap)]
    update = m.RankUpdate(atSeq=SEQ, rank=you.rank, score=you.score, playerCount=PLAYERS)
    return [encode(snap), encode(update)]


async def test_a_repair_builds_the_shared_entries_once_for_every_local_player(
    entries_built: list[str],
) -> None:
    store = RepairStore()
    users = [f"u{rank}" for rank in range(1, PLAYERS + 1)] + [OUTSIDER]
    sockets = Mock(spec=Sockets)
    sockets.players.return_value = users
    service = QuizService(cast("Store", store), Mock(), lambda: 0)
    ticker = Ticker(cast("FeedStore", store), sockets, service, "n1", lambda: 0)
    relay = Mock(spec=Relay)
    await ticker._repair("Q", relay)  # noqa: SLF001 - the repair under test
    assert entries_built == [row.user_id for row in ROWS]  # once per quiz, not once per player
    relay.repaired.assert_called_once()
    sent: dict[str, list[Any]] = {}
    for call in sockets.send_to.call_args_list:
        sent.setdefault(call.args[1], []).append(call.args[2])
    entries = [row.entry() for row in ROWS]
    assert sent == {user_id: expected(user_id, entries) for user_id in users}
