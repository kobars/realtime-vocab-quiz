# AI-ASSISTED: what the relay does with each feed message: control, quiz_ended and stale ranks.
import asyncio
import json
from collections.abc import Sequence
from typing import Any, override
from unittest.mock import Mock

import pytest

from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.fanout import broadcast
from quiz.fanout.broadcast import Relay
from quiz.ports.store import Limits, Place, Ranks, Store

COMPACT = (",", ":")


def published(head: dict[str, Any], entries: list[dict[str, Any]], ranks: list[Any]) -> str:
    """A broadcast as the Redis script publishes it: the head's keys, then the entries last."""
    frame = json.dumps(head, separators=COMPACT)[:-1] + ',"entries":'
    frame += json.dumps(entries, separators=COMPACT) + "}"
    return '{"frame":' + frame + ',"ranks":' + json.dumps(ranks, separators=COMPACT) + "}"


def board(seq: int, player_count: int, entries: list[dict[str, Any]], ranks: list[Any]) -> str:
    head = {"v": 1, "type": "leaderboard", "seq": seq, "rebase": False}
    return published(head | {"playerCount": player_count, "onlineCount": 1}, entries, ranks)


def sent_to(sockets: Mock) -> dict[str, list[bytes]]:
    got: dict[str, list[bytes]] = {}
    for call in sockets.send_to.call_args_list:
        got.setdefault(call.args[1], []).append(call.args[2])
    return got


async def test_session_replaced_closes_the_local_socket_and_reaches_no_client(
    sockets: Mock,
) -> None:
    relay = Relay("Q", Mock(spec=Store), sockets, Limits())
    message = json.dumps({"type": "session_replaced", "uid": "u", "connId": "c-old"})
    assert await relay.relay(message) is False
    sockets.replace.assert_called_once_with("c-old")
    sockets.broadcast.assert_not_called()
    sockets.send_to.assert_not_called()


class EndStore:
    """Ranks every player but the last one, ``p<n>`` at rank 51 + n."""

    def __init__(self, players: Sequence[str]) -> None:
        self.ranked = {user: Place(51 + n, 10 * n) for n, user in enumerate(players[:-1])}

    async def ranks_of(self, _quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        return Ranks(9, "ended", len(user_ids), {u: self.ranked.get(u) for u in user_ids})


def quiz_ended(players: int) -> tuple[dict[str, Any], str]:
    entries = [
        {"rank": r, "userId": f"e{r}", "displayName": f"Émile {r}", "score": 2000 - r}
        for r in range(1, 51)
    ]
    head = {"you": None, "seq": 9, "v": 1, "playerCount": players, "type": "quiz_ended"}
    return head | {"entries": entries}, published(head, entries, [])


def ending(sockets: Mock, players: int) -> tuple[Relay, list[str]]:
    users = [f"p{n}" for n in range(players)]
    sockets.players.return_value = set(users)
    relay = Relay("Q", EndStore(users), sockets, Limits())  # type: ignore[arg-type]
    return relay, users


async def test_each_player_gets_the_end_frame_with_its_own_rank(sockets: Mock) -> None:
    relay, users = ending(sockets, 5)
    frame, message = quiz_ended(5)
    assert await relay.relay(message)
    got, unranked = sent_to(sockets), users[-1]
    for user in users[:-1]:
        row = EndStore(users).ranked[user]
        you = m.You(rank=row.rank, score=row.score)
        assert got[user] == [encode(m.QuizEnded.model_validate({**frame, "you": you}))]
    assert got[unranked] == [message[len('{"frame":') : message.rindex(',"ranks":')].encode()]


async def test_the_end_frame_is_validated_once_for_any_number_of_players(
    sockets: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay, _ = ending(sockets, 1000)
    validate, calls = m.QuizEnded.model_validate, []

    def counted(obj: Any, **kwargs: Any) -> m.QuizEnded:  # noqa: ANN401 - pydantic's input
        calls.append(obj)
        return validate(obj, **kwargs)

    monkeypatch.setattr(m.QuizEnded, "model_validate", counted)
    assert await relay.relay(quiz_ended(1000)[1])
    assert (len(calls), sockets.send_to.call_count) == (1, 1000)


async def test_the_final_ranks_are_read_in_chunks_of_at_most_1000_players(sockets: Mock) -> None:
    relay, users = ending(sockets, 2500)
    store, asked = relay._store, []  # noqa: SLF001 - count the reads of the store under test
    ranks_of = store.ranks_of

    async def counted(quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        asked.append(len(user_ids))
        return await ranks_of(quiz_id, user_ids)

    store.ranks_of = counted  # type: ignore[method-assign]
    assert await relay.relay(quiz_ended(2500)[1])
    assert asked == [1000, 1000, 500]
    got = sent_to(sockets)
    assert all(json.loads(got[user][0])["you"] for user in users[:-1])  # the last one is unranked


def test_quiz_ended_encodes_you_last() -> None:
    """The relay splices each player's ``you`` in place of the shared frame's trailing null."""
    ended = m.QuizEnded(seq=1, playerCount=0, entries=[], you=None)
    assert encode(ended).endswith(b',"you":null}')


class ChunkStore:
    """Reads at a seq one higher per call; player ``p<n>`` is at rank n + 1."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    async def ranks_of(self, _quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        self.asked.append(len(user_ids))
        rows = {u: Place(int(u[1:]) + 1, 0) for u in user_ids}
        return Ranks(5 + len(self.asked), "open", 2500, rows)


async def test_shifted_ranks_are_read_in_chunks_of_at_most_1000_players(sockets: Mock) -> None:
    users = [f"p{n}" for n in range(2500)]
    sockets.players.return_value = users
    store = ChunkStore()
    relay = Relay("Q", store, sockets, Limits())  # type: ignore[arg-type]
    await relay.relay(board(6, 2500, [], []))
    await relay.shifted()
    assert store.asked == [1000, 1000, 500]
    updates = {u: [json.loads(d) for d in sent] for u, sent in sent_to(sockets).items()}
    assert set(updates) == set(users[50:])  # ranks 51 and below: the frame shows the top 50
    for user, (update,) in updates.items():
        chunk = users.index(user) // broadcast.RANKS_BATCH
        assert (update["atSeq"], update["rank"]) == (6 + chunk, users.index(user) + 1)


class HeldStore:
    """A rank read that returns u at rank 60 as of seq 5, once ``release`` is set."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def ranks_of(self, _quiz_id: str, _user_ids: Sequence[str]) -> Ranks:
        await self.release.wait()
        return Ranks(5, "open", 300, {"u": Place(60, 150)})


async def test_a_rank_read_older_than_a_frame_with_the_players_row_sends_nothing(
    sockets: Mock,
) -> None:
    store = HeldStore()
    relay = Relay("Q", store, sockets, Limits())  # type: ignore[arg-type]
    await relay.relay(board(3, 300, [], [["u", 58, 150]]))
    await relay.relay(board(5, 300, [], []))
    reading = asyncio.create_task(relay.shifted())
    await asyncio.sleep(0)
    entry = {"rank": 40, "userId": "u", "displayName": "U", "score": 300}
    await relay.relay(board(6, 300, [entry], []))  # u enters the top 50
    store.release.set()
    await reading
    updates = [json.loads(data) for data in sent_to(sockets)["u"]]
    assert [(u["atSeq"], u["rank"]) for u in updates] == [(3, 58)]  # none from the read at 5


class FailingBatchStore(ChunkStore):
    """Like ``ChunkStore``, but the second read of a round fails while ``failing`` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.failing = True

    @override
    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        if self.failing and len(self.asked) == 1:
            self.asked.append(len(user_ids))
            raise TimeoutError
        return await super().ranks_of(quiz_id, user_ids)


async def test_a_failed_batch_leaves_every_player_to_the_next_shifted_read(sockets: Mock) -> None:
    users = [f"p{n}" for n in range(2500)]
    sockets.players.return_value = users
    store = FailingBatchStore()
    relay = Relay("Q", store, sockets, Limits())  # type: ignore[arg-type]
    await relay.relay(board(6, 2500, [], []))
    with pytest.raises(TimeoutError):
        await relay.shifted()  # the first batch went out, the second failed
    store.failing = False
    await relay.shifted()  # the store is back: every batch is read again
    assert store.asked == [1000, 1000, 1000, 1000, 500]
    assert set(sent_to(sockets)) == set(users[50:])


class FrameDuringTheRead:
    """A rank read at seq 10 of 2,400 players, during which the frame of seq 12 (2,450) arrives."""

    def __init__(self, relay: list[Relay]) -> None:
        self.relay = relay

    async def ranks_of(self, _quiz_id: str, _user_ids: Sequence[str]) -> Ranks:
        await self.relay[0].relay(board(12, 2450, [], []))
        return Ranks(10, "open", 2400, {"u": Place(60, 150)})


async def test_a_rank_read_older_than_a_frame_keeps_the_frames_player_count(
    sockets: Mock,
) -> None:
    holder: list[Relay] = []
    relay = Relay("Q", FrameDuringTheRead(holder), sockets, Limits())  # type: ignore[arg-type]
    holder.append(relay)
    await relay.relay(board(5, 2300, [], []))
    await relay.shifted()
    (update,) = [json.loads(data) for data in sent_to(sockets)["u"]]
    assert (update["atSeq"], update["playerCount"]) == (10, 2450)
