# AI-ASSISTED: store faults and malformed broadcasts never stop the tick loop or the relay early;
# a writable join restarts a loop that ended.
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast, override
from unittest.mock import Mock, call

import pytest

from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.app.service import Connection, QuizService
from quiz.contracts import messages as m
from quiz.domain.errors import DomainError, ErrorCode
from quiz.fanout import tick
from quiz.fanout.broadcast import Relay
from quiz.fanout.tick import Ticker
from quiz.ports.store import End, FeedStore, Limits, Place, Publish, Ranks, Store

SEQ = 3  # the quiz's seq when the loop subscribes


class ScriptedStore:
    """The store of quiz Q at ``SEQ``: ``publish_if_dirty`` plays ``steps`` in turn and raises a
    step that is an error; the feed holds ``messages``, then stays open."""

    limits = Limits(tick_ms=10)

    def __init__(self, *steps: Publish | Exception, messages: Sequence[str] = ()) -> None:
        self.steps, self.messages, self.calls = steps, messages, 0
        self.ranks_error: Exception | None = None
        self.host_ends: list[int | Exception] = []  # end_by_host plays these in turn

    async def end_quiz(self, _quiz_id: str, _reason: str) -> End:
        return End("not_due")

    async def end_by_host(self, _quiz_id: str) -> int:
        step = self.host_ends.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def publish_if_dirty(self, _quiz_id: str, _node_id: str) -> Publish:
        step = self.steps[self.calls]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step

    async def read_seq(self, _quiz_id: str) -> int:
        return SEQ

    async def ranks_of(self, _quiz_id: str, _user_ids: Sequence[str]) -> Ranks:
        if self.ranks_error is not None:
            raise self.ranks_error
        return Ranks(SEQ, "ended", 1, {"u": Place(1, 100)})

    @asynccontextmanager
    async def subscribe(self, _quiz_id: str) -> AsyncIterator[AsyncIterator[str]]:
        yield self._feed()

    async def _feed(self) -> AsyncIterator[str]:
        for message in self.messages:
            yield message
        await asyncio.Event().wait()  # a live subscription: nothing more arrives


def ended(seq: int) -> str:
    frame = {"v": 1, "type": "quiz_ended", "seq": seq, "playerCount": 1, "entries": [], "you": None}
    return json.dumps({"frame": frame, "ranks": []}, separators=(",", ":"))


def last_sent(sockets: Mock) -> dict[str, Any]:
    sockets.send_to.assert_called_once()
    return cast("dict[str, Any]", json.loads(sockets.send_to.call_args.args[2]))


async def run(
    store: ScriptedStore,
    sockets: Mock,
    service: Mock | None = None,
    clock: Callable[[], int] = lambda: 0,
) -> None:
    """Run quiz Q's loop on this node until it ends by itself."""
    service = service or Mock(spec=QuizService)
    ticker = Ticker(cast("FeedStore", store), sockets, service, "n1", clock)
    ticker.open("Q")
    await asyncio.wait_for(ticker._loops["Q"], 1)  # noqa: SLF001 - the loop under test


def logged(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == level]


STORE_BLIPS = pytest.mark.parametrize("blip", [ConnectionError(), TimeoutError()], ids=type)


@STORE_BLIPS
async def test_a_store_blip_logs_a_warning_and_the_loop_keeps_ticking(
    sockets: Mock, caplog: pytest.LogCaptureFixture, blip: Exception, backoffs: list[int]
) -> None:
    store = ScriptedStore(blip, Publish("clean"), Publish("ended", SEQ))
    await run(store, sockets)
    assert (store.calls, backoffs) == (3, [1])
    assert logged(caplog, logging.WARNING) == ["tick of quiz Q: store unreachable"]
    assert logged(caplog, logging.ERROR) == []


async def test_tick_failures_in_a_row_back_off_and_log_once_per_interval(
    sockets: Mock, caplog: pytest.LogCaptureFixture, backoffs: list[int]
) -> None:
    down = ConnectionError()
    store = ScriptedStore(down, down, down, Publish("clean"), down, Publish("ended", SEQ))
    await run(store, sockets, clock=iter([0, 500, 1_000, 1_200]).__next__)
    assert backoffs == [1, 2, 3, 1]  # the subscription held: each failure grows the wait
    assert logged(caplog, logging.WARNING) == ["tick of quiz Q: store unreachable"] * 2


async def test_a_quiz_the_store_lost_ends_the_loop_quietly(
    sockets: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    store = ScriptedStore(DomainError(ErrorCode.QUIZ_NOT_FOUND, "expired"))
    await run(store, sockets)
    assert store.calls == 1
    assert logged(caplog, logging.ERROR) == []


def repairing() -> Mock:
    """A service whose repair read gives player u its snapshot at ``SEQ``."""
    service = Mock(spec=QuizService)
    snapshot = m.Snapshot(
        atSeq=SEQ, status="open", playerCount=1, onlineCount=1, entries=[], you=None
    )
    service.standings.return_value = (Ranks(SEQ, "open", 1, {"u": None}), {"u": (snapshot,)})
    return service


@pytest.fixture
def backoffs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The attempt of each backoff, which then waits for nothing."""
    attempts: list[int] = []

    def backoff_s(attempt: int) -> float:
        attempts.append(attempt)
        return 0

    monkeypatch.setattr(tick, "backoff_s", backoff_s)
    return attempts


async def test_another_refusal_logs_its_traceback_and_the_loop_subscribes_again_with_a_snapshot(
    sockets: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    store = ScriptedStore(DomainError(ErrorCode.UNAVAILABLE, "no reply"), Publish("ended", SEQ))
    await run(store, sockets, repairing())
    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == "fan-out of quiz Q failed: subscribing again"
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], DomainError)
    assert last_sent(sockets)["type"] == "snapshot"  # pub/sub does not replay what was lost


async def test_the_backoff_grows_until_a_tick_goes_through(
    sockets: Mock, backoffs: list[int]
) -> None:
    refusal = DomainError(ErrorCode.UNAVAILABLE, "no reply")
    store = ScriptedStore(refusal, refusal, Publish("clean"), refusal, Publish("ended", SEQ))
    await run(store, sockets, repairing())
    assert backoffs == [0, 1, 0]


async def test_a_quiz_lost_during_the_drop_ends_the_loop_at_the_repair(
    sockets: Mock, backoffs: list[int]
) -> None:
    store = ScriptedStore(DomainError(ErrorCode.UNAVAILABLE, "no reply"))
    service = Mock(spec=QuizService)
    service.standings.side_effect = DomainError(ErrorCode.QUIZ_NOT_FOUND, "expired")
    await run(store, sockets, service)
    assert (backoffs, service.standings.call_count) == ([0], 1)


async def test_an_end_published_before_the_subscribe_ends_the_loop_after_the_grace(
    sockets: Mock,
) -> None:
    store = ScriptedStore(Publish("ended", SEQ))  # its quiz_ended never arrives on the feed
    await run(store, sockets)  # within the 1 s of run: the grace is shorter
    assert store.calls == 1
    assert tick.END_GRACE_S < 1


class EndDuringTheSeqRead(ScriptedStore):
    """The end lands between the subscribe and the seq read: the read already returns its seq,
    and the relay is still reading the final ranks when the tick reports the end."""

    @override
    async def read_seq(self, _quiz_id: str) -> int:
        await asyncio.sleep(0)
        return SEQ

    @override
    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        await asyncio.sleep(0.01)
        return await super().ranks_of(quiz_id, user_ids)


async def test_an_end_published_during_the_seq_read_still_reaches_every_local_player(
    sockets: Mock,
) -> None:
    store = EndDuringTheSeqRead(Publish("ended", SEQ), messages=[ended(SEQ)])
    await run(store, sockets)
    assert (last_sent(sockets)["type"], last_sent(sockets)["you"]) == (
        "quiz_ended",
        {"rank": 1, "score": 100},
    )


class SlowEndDuringTheSeqRead(EndDuringTheSeqRead):
    """As ``EndDuringTheSeqRead``, but the final-rank read outlasts the grace."""

    @override
    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        await asyncio.sleep(0.1)
        return await super().ranks_of(quiz_id, user_ids)


async def test_a_held_end_frame_still_reaches_every_local_player_after_the_grace(
    sockets: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tick, "END_GRACE_S", 0.01)
    store = SlowEndDuringTheSeqRead(Publish("ended", SEQ), messages=[ended(SEQ)])
    await run(store, sockets)
    assert last_sent(sockets)["type"] == "quiz_ended"


async def test_an_unannounced_host_mark_is_confirmed_and_announced_by_the_tick(
    sockets: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    store = ScriptedStore(*[Publish("ended")] * 2)  # a mark, before the deadline
    store.host_ends = [DomainError(ErrorCode.UNAVAILABLE, "not fsynced"), SEQ]
    await run(store, sockets)
    assert (store.calls, store.host_ends) == (2, [])  # the failed fsync is retried next tick
    assert logged(caplog, logging.WARNING) == ["tick of quiz Q: the end mark is not durable yet"]


async def test_the_loop_drops_the_cached_standings_when_it_starts_and_when_it_ends(
    sockets: Mock,
) -> None:
    service = Mock(spec=QuizService)
    await run(ScriptedStore(Publish("ended", SEQ)), sockets, service)
    assert service.drop_cache.call_args_list == [call("Q"), call("Q")]


async def test_a_malformed_broadcast_is_skipped_and_the_next_one_relayed(
    sockets: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    store = ScriptedStore(Publish("ended", SEQ + 1), messages=["not json", ended(SEQ + 1)])
    await run(store, sockets)
    assert last_sent(sockets)["you"] == {"rank": 1, "score": 100}
    assert logged(caplog, logging.ERROR) == ["broadcast not relayed"]


@STORE_BLIPS
async def test_quiz_ended_goes_out_with_you_null_when_the_rank_read_fails(
    sockets: Mock, blip: Exception
) -> None:
    store = ScriptedStore()
    store.ranks_error = blip
    assert await Relay("Q", cast("Store", store), sockets, store.limits).relay(ended(SEQ + 1))
    sent = last_sent(sockets)
    assert (sent["type"], sent["seq"], sent["you"]) == ("quiz_ended", SEQ + 1, None)


async def test_a_frame_with_no_change_time_is_counted_but_not_timed(
    metric: Callable[..., float],
) -> None:
    store = ScriptedStore(Publish("published", SEQ + 1), Publish("published", SEQ + 2, lag_ms=150))
    ticker = Ticker(cast("FeedStore", store), Mock(), Mock(spec=QuizService), "n1", lambda: 0)
    frames, lags = (
        metric("leaderboard_frames_total"),
        metric("leaderboard_publish_lag_seconds_count"),
    )
    lag_s = metric("leaderboard_publish_lag_seconds_sum")
    for _ in range(2):
        await ticker._publish("Q")  # noqa: SLF001 - one publish, without the loop
    assert metric("leaderboard_frames_total") - frames == 2
    assert metric("leaderboard_publish_lag_seconds_count") - lags == 1
    assert metric("leaderboard_publish_lag_seconds_sum") - lag_s == pytest.approx(0.15)


async def test_a_writable_join_restarts_the_loop_of_a_quiz_whose_loop_ended() -> None:
    store = ScriptedStore(*[Publish("ended", SEQ + 1)] * 2, messages=[ended(SEQ + 1)])
    registry = Registry(cast("Store", store), 10_000)
    ticker = Ticker(cast("FeedStore", store), registry, Mock(spec=QuizService), "n1", lambda: 0)
    registry.watcher = ticker
    sender = Mock(spec=Sender, close_code=None)
    registry.bind(Connection("c1", "u1", quiz_id="Q", present=True), sender)
    ended_loop = ticker._loops["Q"]  # noqa: SLF001 - the loop under test
    await asyncio.wait_for(ended_loop, 1)  # quiz_ended relayed; the socket stays bound
    registry.bind(Connection("c2", "u2", quiz_id="Q", read_only=True), sender)
    assert ticker._loops["Q"] is ended_loop  # noqa: SLF001 - a read-only join needs no tick
    registry.bind(Connection("c3", "u3", quiz_id="Q", present=True), sender)  # the id was reused
    assert ticker._loops["Q"] is not ended_loop  # noqa: SLF001
    await ticker.stop()
