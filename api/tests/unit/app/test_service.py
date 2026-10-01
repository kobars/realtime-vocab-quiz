# AI-ASSISTED: use-case tests: protocol messages in, replies out, on the memory store and a clock.
import logging
from collections.abc import Sequence
from typing import Any, Literal

import pytest
from redis import exceptions as redis_errors

from quiz.adapters.memory import MemoryStore
from quiz.adapters.redis import RedisStore
from quiz.app.service import Connection, QuizService
from quiz.contracts import messages as m
from quiz.domain import errors as domain
from quiz.domain.session import Question
from quiz.obs import metrics
from quiz.ports.questions import BankQuestion
from quiz.ports.store import End, Limits, Page, Ranks, Snapshot

QUIZ, N = "VOCAB-1", 3
E, SID = m.ErrorCode, "-0000-4000-8000-000000000000"
type Refusal = tuple[m.ErrorCode, int | None]


def answer(i: int, choice: int = 1, sid: int = 1) -> m.Answer:
    return m.Answer(questionIndex=i, choiceIndex=choice, submissionId=f"{sid:08x}{SID}")


class Bank:
    async def questions(self, quiz_id: str) -> tuple[BankQuestion, ...] | None:
        del quiz_id
        return tuple(BankQuestion(f"q{i}", f"word {i}?", ("a", "b", "c", "d"), 1) for i in range(N))

    async def title(self, quiz_id: str) -> str | None:
        return quiz_id


class SpyStore(MemoryStore):
    def __init__(self) -> None:
        self.now, self.snapshots, self.pages, self.ends = [1_000_000], 0, 0, 0
        super().__init__(lambda: self.now[0])

    async def snapshot(self, quiz_id: str, user_id: str | None) -> Snapshot:
        self.snapshots += 1
        return await super().snapshot(quiz_id, user_id)

    async def standings_page(self, quiz_id: str, offset: int, limit: int) -> Page:
        self.pages += 1
        return await super().standings_page(quiz_id, offset, limit)

    async def end_quiz(self, quiz_id: str, reason: Literal["deadline", "host"]) -> End:
        self.ends += 1
        return await super().end_quiz(quiz_id, reason)


@pytest.fixture
async def store() -> SpyStore:
    store = SpyStore()
    questions = tuple(Question(f"q{i}", 1) for i in range(N))
    await store.create_quiz(QUIZ, questions, window_ms=60_000, time_limit_ms=20_000)
    return store


@pytest.fixture
def service(store: SpyStore) -> QuizService:
    return QuizService(store, Bank(), lambda: store.now[0])


async def send(service: QuizService, conn: Connection, msg: m.ClientMessage) -> list[Any]:
    return list((await service.handle(conn, msg)).replies)


async def refused(service: QuizService, conn: Connection, msg: m.ClientMessage) -> Refusal:
    outcome = await service.handle(conn, msg)
    [error] = outcome.replies
    assert isinstance(error, m.ProtocolError)
    assert error.requestType == msg.type
    return error.code, outcome.close_code


async def joined(service: QuizService, user: str = "a") -> Connection:
    conn = Connection(f"c-{user}", user)
    [reply] = await send(service, conn, m.Join(quizId=QUIZ, displayName=f"  {user.upper()} "))
    assert (reply.displayName, reply.cursor, reply.questionCount) == (user.upper(), -1, N)
    return conn


async def test_question_answer_and_finish(service: QuizService) -> None:
    conn = await joined(service)
    [q] = await send(service, conn, m.Next(questionIndex=0))
    assert (q.prompt, q.choices, q.remainingMs) == ("word 0?", list("abcd"), 20_000)
    [result] = await send(service, conn, answer(0))
    assert (result.correctChoiceIndex, result.pointsAwarded, result.score) == (1, 150, 150)
    assert await send(service, conn, answer(0)) == [result]  # a replay is identical
    assert await refused(service, conn, answer(0, 2, sid=2)) == (E.ALREADY_ANSWERED, None)
    assert await refused(service, conn, answer(2, sid=3)) == (E.QUESTION_NOT_OPEN, None)
    [finished] = await send(service, conn, m.Next(questionIndex=N))
    assert finished == m.Finished(atSeq=0, score=150, rank=1, playerCount=1)


async def test_join_errors_and_requests_before_join(service: QuizService) -> None:
    conn, unknown = Connection("c-a", "a"), m.Join(quizId="NOPE-1", displayName="A")
    page, resync = m.GetLeaderboard(offset=0, limit=10), m.Resync(lastSeq=0)
    for msg in (m.Next(questionIndex=0), answer(0), resync, page):
        assert await refused(service, conn, msg) == (E.NOT_JOINED, None)
    assert await send(service, conn, m.Ping()) == [m.Pong(seq=None)]
    assert await refused(service, conn, unknown) == (E.QUIZ_NOT_FOUND, None)
    blank = m.Join(quizId=QUIZ, displayName="   ")
    assert await refused(service, conn, blank) == (E.INVALID_MESSAGE, None)
    conn = await joined(service)  # the failed joins bound nothing
    assert (await send(service, conn, m.Join(quizId=QUIZ, displayName="A")))[0].cursor == -1
    assert await refused(service, conn, unknown) == (E.INVALID_STATE, None)
    assert await send(service, conn, m.Ping()) == [m.Pong(seq=0)]


async def test_join_after_end_is_read_only(service: QuizService, store: SpyStore) -> None:
    store.now[0] += 60_000
    conn = Connection("c-a", "a")
    snapshot, error = await send(service, conn, m.Join(quizId=QUIZ, displayName="A"))
    assert (snapshot.status, snapshot.you, error.code) == ("ended", None, E.QUIZ_ENDED)
    assert await refused(service, conn, m.Next(questionIndex=0)) == (E.QUIZ_ENDED, None)
    [page] = await send(service, conn, m.GetLeaderboard(offset=0, limit=5))
    assert page.final


async def test_resync_answers_a_snapshot_at_most_once_a_second(
    service: QuizService, store: SpyStore
) -> None:
    conn = await joined(service)
    [snapshot] = await send(service, conn, m.Resync(lastSeq=0))
    entries, you = [m.Entry(rank=1, userId="a", displayName="A", score=0)], m.You(rank=1, score=0)
    assert snapshot == m.Snapshot(
        atSeq=0, status="open", playerCount=1, onlineCount=1, entries=entries, you=you
    )
    store.now[0] += 999
    assert await refused(service, conn, m.Resync(lastSeq=0)) == (E.RATE_LIMITED, None)
    store.now[0] += 1
    assert await send(service, conn, m.Resync(lastSeq=0)) == [snapshot]


async def test_snapshot_caches_the_shared_part_per_seq(
    service: QuizService, store: SpyStore
) -> None:
    conn = await joined(service)
    await send(service, conn, m.Next(questionIndex=0))
    first = await service.snapshot(QUIZ, "a")
    await send(service, conn, answer(0))  # no tick yet: the seq stays 0
    second = await service.snapshot(QUIZ, "a")
    assert store.snapshots == 1
    assert (second.entries, second.you) == (first.entries, m.You(rank=1, score=150))
    assert (await store.publish_if_dirty(QUIZ, "n1")).seq == 1
    third = await service.snapshot(QUIZ, "a")
    assert (store.snapshots, third.atSeq, third.entries[0].score) == (2, 1, 150)
    store.now[0] += 60_000  # the deadline passes before quiz_ended is announced
    assert (await service.snapshot(QUIZ, "a")).status == "ended"


async def test_resync_adds_rank_update_outside_the_shown_entries(service: QuizService) -> None:
    conns = [await joined(service, f"u{i:03}") for i in range(m.FULL_LIST_MAX + 1)]
    await send(service, conns[-1], m.Next(questionIndex=0))
    await send(service, conns[-1], answer(0))  # u200 ranks first, so u048 is 50th, u049 51st
    [top] = await send(service, conns[48], m.Resync(lastSeq=0))
    snapshot, update = await send(service, conns[49], m.Resync(lastSeq=0))
    assert len(top.entries) == m.TOP_N
    assert (top.you, snapshot.you) == (m.You(rank=50, score=0), m.You(rank=51, score=0))
    assert update == m.RankUpdate(atSeq=0, rank=51, score=0, playerCount=201)


async def test_resync_rank_update_follows_the_configured_full_list_max() -> None:
    store = MemoryStore(lambda: 1_000_000, Limits(200, 1, 2))
    questions = tuple(Question(f"q{i}", 1) for i in range(N))
    await store.create_quiz(QUIZ, questions, window_ms=60_000, time_limit_ms=20_000)
    service = QuizService(store, Bank(), lambda: 1_000_000)
    conns = [await joined(service, user) for user in ("a", "b", "c")]
    snapshot, update = await send(service, conns[1], m.Resync(lastSeq=0))
    assert ([e.userId for e in snapshot.entries], snapshot.you) == (["a"], m.You(rank=2, score=0))
    assert update == m.RankUpdate(atSeq=0, rank=2, score=0, playerCount=3)


async def test_session_replaced_closes_the_older_socket(service: QuizService) -> None:
    old = await joined(service)
    outcome = await service.handle(Connection("c-new", "a"), m.Join(quizId=QUIZ, displayName="A"))
    assert outcome.replaced_conn_id == "c-a"
    assert await refused(service, old, m.Next(questionIndex=0)) == (E.SESSION_REPLACED, 4001)


@pytest.mark.parametrize("code", list(domain.ErrorCode))
def test_every_domain_code_has_the_same_protocol_code(code: domain.ErrorCode) -> None:
    assert E(code.value).name == code.name


async def test_store_faults_are_internal_with_a_log_reference_or_unavailable(
    service: QuizService, store: SpyStore, caplog: pytest.LogCaptureFixture
) -> None:
    conn, faults = await joined(service), [ConnectionError("down"), RuntimeError("boom")]

    async def fault(*_: object) -> None:
        raise faults.pop()

    store.serve_next = fault  # type: ignore[method-assign, assignment]
    with caplog.at_level(logging.ERROR):
        outcome = await service.handle(conn, m.Next(questionIndex=0))
    [error] = outcome.replies
    assert isinstance(error, m.ProtocolError)
    assert (error.code, outcome.close_code, "boom" in error.message) == (E.INTERNAL, 1011, False)
    assert error.message.rsplit(" ", 1)[-1] in caplog.records[0].getMessage()
    assert await refused(service, conn, m.Next(questionIndex=0)) == (E.UNAVAILABLE, None)


class DownRedis:  # loads scripts, then fails as redis-py fails when Redis is unreachable
    async def script_load(self, script: str) -> str:
        return str(hash(script))

    async def evalsha(self, *_: object) -> None:
        raise redis_errors.ConnectionError

    async def get(self, *_: object) -> None:
        raise redis_errors.TimeoutError


async def test_redis_faults_are_unavailable_and_ping_answers_null() -> None:
    store = RedisStore(DownRedis())  # type: ignore[arg-type]
    await store.start()
    service = QuizService(store, Bank(), lambda: 0)
    conn = Connection("c-a", "a")
    assert await refused(service, conn, m.Join(quizId=QUIZ, displayName="A")) == (
        E.UNAVAILABLE,
        None,
    )
    conn.quiz_id = QUIZ
    assert await send(service, conn, m.Ping()) == [m.Pong(seq=None)]


async def test_ping_reads_only_the_counter(service: QuizService, store: SpyStore) -> None:
    conn = await joined(service)
    assert await send(service, conn, m.Ping()) == [m.Pong(seq=0)]
    assert store.pages == 0


async def test_snapshot_never_mixes_stale_standings_with_a_fresh_own_row(
    service: QuizService,
) -> None:
    a = await joined(service, "a")
    await send(service, a, m.Resync(lastSeq=0))
    b = await joined(service, "b")  # same tick: the seq stays 0
    [snapshot] = await send(service, b, m.Resync(lastSeq=0))  # and no rank_update
    assert (snapshot.playerCount, [e.userId for e in snapshot.entries]) == (2, ["a", "b"])
    assert snapshot.you == m.You(rank=2, score=0)


async def test_snapshot_rereads_both_parts_when_a_join_lands_between_reads(
    service: QuizService, store: SpyStore
) -> None:
    await joined(service, "a")
    ranks_of = store.ranks_of

    async def join_first(quiz_id: str, users: Sequence[str]) -> Ranks:
        await store.join(quiz_id, "b", "B", "c-b")
        return await ranks_of(quiz_id, users)

    store.ranks_of = join_first  # type: ignore[method-assign, assignment]
    snapshot = await service.snapshot(QUIZ, "b")
    assert (snapshot.playerCount, len(snapshot.entries), snapshot.you) == (
        2,
        2,
        m.You(rank=2, score=0),
    )


async def test_joined_echoes_the_stored_name(service: QuizService) -> None:
    await joined(service, "a")
    rejoin = m.Join(quizId=QUIZ, displayName="Renamed")
    [reply] = await send(service, Connection("c-new", "a"), rejoin)
    assert reply.displayName == "A"


async def test_dropped_cache_refetches_at_the_same_seq(
    service: QuizService, store: SpyStore
) -> None:
    await joined(service)
    await service.snapshot(QUIZ, "a")
    await service.snapshot(QUIZ, "a")
    assert store.snapshots == 1
    service.drop_cache(QUIZ)
    await service.snapshot(QUIZ, "a")
    service.drop_cache()
    await service.snapshot(QUIZ, "a")
    assert store.snapshots == 3


async def test_first_writes_after_the_deadline_announce_the_end(
    service: QuizService, store: SpyStore
) -> None:
    conn = await joined(service)
    await send(service, conn, m.Next(questionIndex=0))
    store.now[0] += 60_000
    assert await refused(service, conn, m.Next(questionIndex=1)) == (E.QUIZ_ENDED, None)
    assert store.ends == 1
    assert await refused(service, conn, answer(0)) == (E.QUIZ_ENDED, None)
    assert store.ends == 2  # the memory store's refusals never carry end_seq
    late = m.Join(quizId=QUIZ, displayName="B")
    [snapshot, error] = await send(service, Connection("c-b", "b"), late)
    assert (snapshot.status, error.code, store.ends) == ("ended", E.QUIZ_ENDED, 3)


async def test_clock_step_back_counts_once_and_never_on_a_replay(
    service: QuizService, store: SpyStore
) -> None:
    before = metrics.REDIS_CLOCK_STEP._value.get()  # noqa: SLF001 - the counter's raw value
    conn = await joined(service)
    await send(service, conn, m.Next(questionIndex=0))
    store.now[0] -= 5
    [result] = await send(service, conn, answer(0))
    assert result.pointsAwarded == 150  # elapsed is clamped to 0
    assert await send(service, conn, answer(0)) == [result]
    assert metrics.REDIS_CLOCK_STEP._value.get() == before + 1  # noqa: SLF001
