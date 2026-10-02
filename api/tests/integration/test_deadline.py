# AI-ASSISTED: end_quiz.lua on a real Redis: the host mark, then one quiz_ended broadcast; a mark
# that is not yet durable reads open and refuses writes as UNAVAILABLE.
import asyncio
import json
import uuid

import pytest
from redis.asyncio import Redis

from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.app.service import Connection, QuizService
from quiz.contracts import messages as m
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import End, Publish


async def test_end_quiz_is_idempotent(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    await redis_store.join(quiz_id, "a", "Ann", "c-a")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(keys.events)
    confirm = await pubsub.get_message(timeout=5)
    assert confirm is not None
    assert confirm["type"] == "subscribe"
    assert await redis_store.end_quiz(quiz_id, "host") == End("marked")
    assert await redis_client.get(keys.dirty) is None
    assert await redis_store.end_quiz(quiz_id, "host") == End("ended", 1)
    for reason in ("host", "deadline"):
        assert await redis_store.end_quiz(quiz_id, reason) == End("ended", 1)
    assert await redis_store.publish_if_dirty(quiz_id, "n1") == Publish("ended", 1)
    messages = []
    while message := await pubsub.get_message(timeout=0.1):
        messages.append(json.loads(message["data"]))
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    head = {"v": 1, "type": "quiz_ended", "seq": 1, "playerCount": 1, "you": None}
    entry = {"rank": 1, "userId": "a", "displayName": "Ann", "score": 0}
    assert messages == [{"frame": {**head, "entries": [entry]}, "ranks": []}]
    assert await redis_client.get(keys.seq) == "1"
    assert await redis_client.hget(keys.meta, "endSeq") == "1"


async def test_host_end_announces_only_after_the_mark_is_fsynced(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    seen, wait = [], redis_store._fsynced  # noqa: SLF001 - the WAITAOF step under test

    async def watched(conn: Redis) -> int:
        end_seq = await redis_client.hget(keys.meta, "endSeq")
        seen.append((end_seq, await redis_client.get(keys.seq)))
        return await wait(conn)  # the real WAITAOF 1 0 2000 (the test Redis runs with AOF on)

    monkeypatch.setattr(redis_store, "_fsynced", watched)
    assert await redis_store.end_by_host(quiz_id) == 1
    assert seen == [(None, "0")]  # marked, not yet announced, while it waited
    assert await redis_store.end_by_host(quiz_id) == 1  # idempotent; no second wait
    assert len(seen) == 1


async def test_host_end_without_the_fsync_announces_nothing(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)

    async def no_fsync(_: Redis) -> int:
        return 0

    monkeypatch.setattr(redis_store, "_fsynced", no_fsync)
    with pytest.raises(DomainError) as refused:
        await redis_store.end_by_host(quiz_id)
    assert refused.value.code is ErrorCode.UNAVAILABLE
    assert await redis_client.hget(keys.meta, "endSeq") is None
    assert await redis_client.get(keys.seq) == "0"


async def test_a_retry_after_a_failed_fsync_waits_for_its_own_fsync(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    seen, wait = [], redis_store._fsynced  # noqa: SLF001 - the WAITAOF step under test

    async def fails_once(conn: Redis) -> int:
        seen.append(await redis_client.hget(keys.meta, "endSeq"))
        return 0 if len(seen) == 1 else await wait(conn)

    monkeypatch.setattr(redis_store, "_fsynced", fails_once)
    with pytest.raises(DomainError) as refused:
        await redis_store.end_by_host(quiz_id)
    assert refused.value.code is ErrorCode.UNAVAILABLE
    assert await redis_store.end_by_host(quiz_id) == 1
    assert seen == [None, None]  # the retry found the mark, yet waited again before announcing


async def test_overlapping_host_ends_each_wait_for_the_fsync_before_announcing(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    seen, wait = [], redis_store._fsynced  # noqa: SLF001 - the WAITAOF step under test
    first_waits, release = asyncio.Event(), asyncio.Event()

    async def first_held(conn: Redis) -> int:
        seen.append(await redis_client.hget(keys.meta, "endSeq"))
        if len(seen) == 1:
            first_waits.set()
            await release.wait()
        return await wait(conn)

    monkeypatch.setattr(redis_store, "_fsynced", first_held)
    first = asyncio.create_task(redis_store.end_by_host(quiz_id))
    await first_waits.wait()
    try:
        assert await redis_store.end_by_host(quiz_id) == 1
    finally:
        release.set()
    assert await first == 1
    assert seen == [None, None]  # the second end waited for its own fsync, not the first one's


async def test_an_unconfirmed_host_mark_reads_open_and_refuses_writes_as_unavailable(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    create = redis_store.create_quiz
    await create(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    service, player = (
        QuizService(redis_store, MockQuestionBank.load(), lambda: 0),
        Connection("c-a", "a"),
    )
    await service.handle(player, m.Join(quizId=quiz_id, displayName="A"))
    await redis_store.serve_next(quiz_id, "a", 0, "c-a")
    assert await redis_store.end_quiz(quiz_id, "mark") == End("marked")  # its fsync is pending

    async def replies(conn: Connection, msg: m.ClientMessage) -> list[m.ServerMessage]:
        return list((await service.handle(conn, msg)).replies)

    answer = m.Answer(questionIndex=0, choiceIndex=1, submissionId=str(uuid.uuid4()))
    [refused] = await replies(player, answer)
    assert isinstance(refused, m.ProtocolError)
    assert refused.code is m.ErrorCode.UNAVAILABLE
    assert (await redis_store.snapshot(quiz_id, "a")).status == "open"
    late = Connection("c-b", "b")
    [refused] = await replies(late, m.Join(quizId=quiz_id, displayName="B"))
    assert isinstance(refused, m.ProtocolError)
    assert (refused.code, late.read_only) == (m.ErrorCode.UNAVAILABLE, False)
    await redis_client.hdel(keys.meta, "endedMs")  # the mark is lost before its fsync
    [scored] = await replies(player, answer)
    assert isinstance(scored, m.AnswerResult)
    assert await redis_store.end_by_host(quiz_id) == 1  # control: an announced end
    another = m.Answer(questionIndex=0, choiceIndex=1, submissionId=str(uuid.uuid4()))
    [ended] = await replies(player, another)
    assert isinstance(ended, m.ProtocolError)
    assert ended.code is m.ErrorCode.QUIZ_ENDED
    assert (await redis_store.snapshot(quiz_id, "a")).status == "ended"
    snapshot, ended = await replies(late, m.Join(quizId=quiz_id, displayName="B"))
    assert isinstance(snapshot, m.Snapshot)
    assert isinstance(ended, m.ProtocolError)
    assert (snapshot.status, ended.code, late.read_only) == ("ended", m.ErrorCode.QUIZ_ENDED, True)
