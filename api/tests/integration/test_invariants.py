# AI-ASSISTED: the scoring and seq invariants on a real Redis under 200 joins and 1,000 answers.
import asyncio
import contextlib
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.config import Settings
from quiz.contracts.messages import FULL_LIST_MAX
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.events import AnswerScored
from quiz.domain.session import Question
from quiz.main import connect_redis
from quiz.ports.store import Answered, Served

PLAYERS = FULL_LIST_MAX  # every player is in each leaderboard frame
QUESTIONS = (Question("q0", 1), Question("q1", 3))
NODES = ("n1", "n2")

pytestmark = pytest.mark.usefixtures("redis_client")  # it deletes this test's keys afterwards


@pytest.fixture
async def store(redis_url: str, redis_prefix: str) -> AsyncIterator[RedisStore]:
    """A store on the service's default connection pool, so the bursts queue as they do there."""
    client = connect_redis(Settings(redis_url=redis_url))
    store = RedisStore(client, prefix=redis_prefix)
    await store.start()
    yield store
    await client.aclose()


@pytest.fixture
async def quiz_id(store: RedisStore) -> str:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=20_000)
    return quiz_id


@pytest.fixture
async def users(store: RedisStore, quiz_id: str) -> list[str]:
    """Every player joins at once."""
    users = [f"u{n:03}" for n in range(PLAYERS)]
    await asyncio.gather(*(store.join(quiz_id, u, u, f"c-{u}") for u in users))
    return users


async def test_concurrent_joins_get_unique_ranks(
    store: RedisStore, quiz_id: str, users: list[str]
) -> None:
    page = await store.standings_page(quiz_id, 0, PLAYERS)
    assert page.player_count == PLAYERS
    assert [row.rank for row in page.rows] == list(range(1, PLAYERS + 1))
    assert sorted(row.user_id for row in page.rows) == users
    assert await store.read_seq(quiz_id) == 0  # joins set dirty and never move seq


async def ticking(store: RedisStore, quiz_id: str, stop: asyncio.Event) -> None:
    """Two nodes tick every 50 ms; after ``stop`` they go on until nothing is left to publish."""
    while True:
        replies = await asyncio.gather(*(store.publish_if_dirty(quiz_id, n) for n in NODES))
        if stop.is_set() and all(reply.status == "clean" for reply in replies):
            return
        await asyncio.sleep(0.05)


async def answer_wave(
    store: RedisStore, quiz_id: str, users: list[str], index: int
) -> dict[str, AnswerScored]:
    """Five answers per player at once: three copies of one submission and two of another.

    The two submissions pick different choices, so a second scoring would show in the total.
    Returns each player's one scored result."""
    calls, owners = [], []
    for n, user in enumerate(users):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        for sid, choice in [(first, n % 4)] * 3 + [(second, (n + 1) % 4)] * 2:
            calls.append(store.apply_answer(quiz_id, user, index, choice, sid, f"c-{user}"))
            owners.append(user)
    outcomes = await asyncio.gather(*calls, return_exceptions=True)
    by_user: dict[str, list[object]] = {user: [] for user in users}
    for user, outcome in zip(owners, outcomes, strict=True):
        by_user[user].append(outcome)
    scored = {}
    for user, results in by_user.items():
        answered = [r.result for r in results if isinstance(r, Answered)]
        refused = [r for r in results if not isinstance(r, Answered)]
        stored = set(answered)  # every copy of the submission that won: one stored result
        assert len(stored) == 1, f"{user} scored more than once: {stored}"
        assert len(answered) in {2, 3}
        for error in refused:
            assert isinstance(error, DomainError), error
            assert error.code is ErrorCode.ALREADY_ANSWERED
        scored[user] = stored.pop()
    return scored


async def test_seq_has_no_gaps_under_concurrent_answers(
    store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str, users: list[str]
) -> None:
    keys = quiz_keys(quiz_id, redis_prefix)
    events = redis_client.pubsub()
    stop = asyncio.Event()
    ticker: asyncio.Task[None] | None = None
    try:
        await events.subscribe(keys.events)
        confirm = await events.get_message(timeout=5)  # subscribed before the first tick publishes
        assert confirm is not None
        assert confirm["type"] == "subscribe"
        events.ignore_subscribe_messages = True
        ticker = asyncio.create_task(ticking(store, quiz_id, stop))
        waves = []
        for index in range(len(QUESTIONS)):
            served = await asyncio.gather(
                *(store.serve_next(quiz_id, u, index, f"c-{u}") for u in users)
            )
            assert all(isinstance(s, Served) for s in served)
            waves.append(await answer_wave(store, quiz_id, users, index))
        last = len(QUESTIONS) - 1
        retries = await asyncio.gather(  # a late retry of the last scored submission replays it
            *(
                store.apply_answer(quiz_id, u, last, r.choice_index, r.submission_id, f"c-{u}")
                for u, r in waves[-1].items()
            )
        )
        assert [(a.result, a.replay) for a in retries] == [(waves[-1][u], True) for u in users]
        stop.set()
        await asyncio.wait_for(ticker, timeout=10)

        expected = {u: sum(wave[u].points for wave in waves) for u in users}
        assert {u: waves[-1][u].total for u in users} == expected
        totals = await redis_client.hgetall(keys.totals)
        assert {u: int(totals.get(u, 0)) for u in users} == expected
        assert await redis_client.hlen(keys.answered) == PLAYERS * len(QUESTIONS)  # scored once
        page = await store.standings_page(quiz_id, 0, PLAYERS)
        assert {row.user_id: row.score for row in page.rows} == expected
        assert Counter(row.rank for row in page.rows) == Counter(range(1, PLAYERS + 1))

        frames = []
        while message := await events.get_message(timeout=0.2):
            frames.append(json.loads(message["data"])["frame"])
    finally:
        if ticker is not None and not ticker.done():
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        await events.aclose()  # type: ignore[no-untyped-call]
    assert [frame["seq"] for frame in frames] == list(range(1, len(frames) + 1))
    assert await store.read_seq(quiz_id) == len(frames)
    final = {entry["userId"]: entry["score"] for entry in frames[-1]["entries"]}
    assert final == expected  # the last frame lost no scored answer
