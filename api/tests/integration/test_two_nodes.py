# AI-ASSISTED: two app instances on one Redis serve one quiz as one: delivery within a tick, seq
# order, tick rate, the snapshot after a dropped subscription, rank_update, presence, convergence.
import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import uvicorn
from redis.asyncio import Redis
from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Origin, Subprotocol

from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.ws.heartbeat import server_config
from quiz.config import Settings
from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.domain.session import Question
from quiz.main import Services, create_app, services_of
from quiz.ports.questions import BankQuestion

ORIGIN, TICK_S = "http://localhost:8080", 0.2
QUESTIONS = tuple(
    BankQuestion(f"q{i}", f"word {i}", ("a", "b", "c", "d"), i % 4) for i in range(10)
)
PUSHED = {"leaderboard", "rank_update", "quiz_ended"}  # never the reply to a request
Got = list[tuple[float, dict[str, Any]]]


class Player:
    """A protocol client that records every message it gets, with the time it arrived."""

    def __init__(self, ws: ClientConnection, user_id: str) -> None:
        self.ws, self.user_id, self.got = ws, user_id, Got()
        self._replies = asyncio.Queue[dict[str, Any]]()
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for text in self.ws:
            msg = json.loads(text)
            self.got.append((time.monotonic(), msg))
            if msg["type"] not in PUSHED:
                self._replies.put_nowait(msg)

    async def ask(self, msg: m.ClientMessage) -> dict[str, Any]:
        await self.ws.send(encode(msg).decode())
        return await asyncio.wait_for(self._replies.get(), 5)

    async def join(self, quiz_id: str) -> None:
        assert (await self.ask(m.Join(quizId=quiz_id, displayName="P")))["type"] == "joined"
        assert (await self.ask(m.Resync(lastSeq=0)))["type"] == "snapshot"

    async def answer(self, i: int) -> tuple[float, int]:
        """Answer question i correctly; when it was sent, and the new total."""
        await self.ask(m.Next(questionIndex=i))
        sent, choice = time.monotonic(), QUESTIONS[i].correct_choice
        answer = m.Answer(questionIndex=i, choiceIndex=choice, submissionId=str(uuid.uuid4()))
        return sent, (await self.ask(answer))["score"]

    def of(self, kind: str) -> Got:
        return [(t, msg) for t, msg in self.got if msg["type"] == kind]

    def applied(self) -> list[dict[str, Any]]:
        """The leaderboards in arrival order: each is one past the newest seq seen, no gap."""
        last: int | None = None
        frames = []
        for _, msg in self.got:
            if msg["type"] == "snapshot":
                last = max(msg["atSeq"], last or 0)
            elif msg["type"] == "leaderboard" and msg["seq"] != last:
                assert last is None or msg["seq"] == last + 1, f"seq {last}, then {msg['seq']}"
                last = msg["seq"]
                frames.append(msg)
        return frames


@dataclass
class Node:
    services: Services
    port: int
    players: list[Player] = field(default_factory=list)

    async def player(self, quiz_id: str) -> tuple[Player, str]:
        """A new user's socket on this node, joined; and its session token."""
        identity, token = await self.services.tickets.create_session("P")
        return await self.rejoin(quiz_id, identity.user_id, token), token

    async def rejoin(self, quiz_id: str, user_id: str, token: str) -> Player:
        ticket = await self.services.tickets.issue_ticket(token)
        url = f"ws://127.0.0.1:{self.port}/ws?ticket={ticket}"
        ws = await connect(url, origin=Origin(ORIGIN), subprotocols=[Subprotocol("quiz.v1")])
        self.players.append(player := Player(ws, user_id))
        await player.join(quiz_id)
        return player


@asynccontextmanager
async def node(settings: Settings) -> AsyncIterator[Node]:
    app = create_app(settings)
    server = uvicorn.Server(server_config(app, settings, "127.0.0.1", 0))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        assert not serving.done(), "the server stopped during startup"
        await asyncio.sleep(0.01)
    running = Node(services_of(app), server.servers[0].sockets[0].getsockname()[1])
    try:
        yield running
    finally:
        for player in running.players:
            await player.ws.close()
        server.should_exit = True
        await serving


@pytest.fixture
def quiz_id(monkeypatch: pytest.MonkeyPatch) -> str:
    quiz_id = f"N-{uuid.uuid4().hex[:8].upper()}"
    monkeypatch.setattr(MockQuestionBank, "load", lambda: MockQuestionBank({quiz_id: QUESTIONS}))
    return quiz_id


@asynccontextmanager
async def cluster(
    redis_url: str, quiz_id: str, **settings: int
) -> AsyncIterator[tuple[Node, Node]]:
    """Nodes A and B on one Redis, with the quiz created."""
    on_redis = Settings(store="redis", redis_url=redis_url, **settings)  # type: ignore[arg-type]
    a_settings, b_settings = (on_redis.model_copy(update={"node_id": n}) for n in "AB")
    async with node(a_settings) as a, node(b_settings) as b:
        questions = tuple(Question(q.question_id, q.correct_choice) for q in QUESTIONS)
        create = a.services.store.create_quiz
        await create(quiz_id, questions, window_ms=600_000, time_limit_ms=20_000)
        yield a, b


async def play(player: Player, gap_s: float) -> list[tuple[float, int]]:
    answers = []
    for i in range(len(QUESTIONS)):
        answers.append(await player.answer(i))
        await asyncio.sleep(gap_s)
    return answers


def shown_at(reader: Player, user_id: str, total: int) -> float:
    """When the reader first got a leaderboard that shows the user with at least that total."""
    return next(
        t
        for t, msg in reader.of("leaderboard")
        if any(e["userId"] == user_id and e["score"] >= total for e in msg["entries"])
    )


async def test_answers_reach_both_nodes_within_a_tick_in_seq_order(
    redis_url: str, quiz_id: str
) -> None:
    async with cluster(redis_url, quiz_id) as (a, b):
        players = [(await n.player(quiz_id))[0] for n in (a, a, b, b)]
        start = time.monotonic()
        answers = await asyncio.gather(*(play(p, 0.15) for p in players))
        end = time.monotonic()
        await asyncio.sleep(2 * TICK_S)
    for writer, sent in zip(players, answers, strict=True):
        readers = players[2:] if writer in players[:2] else players[:2]  # the other node's
        delays = [shown_at(r, writer.user_id, total) - t for r in readers for t, total in sent]
        assert max(delays) < TICK_S + 0.15
    seqs = [[f["seq"] for f in p.applied()] for p in players]
    assert all(s[-1] == seqs[0][-1] for s in seqs)  # every socket ends on the newest frame
    times = [t for t, msg in players[0].of("leaderboard") if start <= t <= end]
    assert len(times) >= 6  # ticking all along
    assert (len(times) - 1) / (times[-1] - times[0]) <= 5.1  # one publish per tick per quiz


async def test_clients_converge_after_quiet_period(redis_url: str, quiz_id: str) -> None:
    async with cluster(redis_url, quiz_id) as (a, b):
        players = [(await n.player(quiz_id))[0] for n in (a, b, a, b)]
        await asyncio.gather(*(play(p, 0.01 * n) for n, p in enumerate(players)))
        await asyncio.sleep(3 * TICK_S)  # quiet: the last change gets its frame
        final = await a.services.store.snapshot(quiz_id, None)
    expected = [[r.rank, r.user_id, r.score] for r in final.rows]
    for player in players:
        last = player.applied()[-1]
        assert last["seq"] == final.at_seq
        assert [[e["rank"], e["userId"], e["score"]] for e in last["entries"]] == expected


async def test_a_dropped_subscription_gets_each_local_socket_a_snapshot(
    redis_url: str, quiz_id: str
) -> None:
    async with cluster(redis_url, quiz_id) as (a, b), Redis.from_url(redis_url) as admin:
        (pa, _), (pb, _) = await a.player(quiz_id), await b.player(quiz_id)
        await asyncio.sleep(2 * TICK_S)
        assert await admin.client_kill_filter(_type="pubsub") >= 2  # both nodes' subscriptions
        await asyncio.sleep(1.0)  # the first backoff is at most 250 ms
        assert [len(p.of("snapshot")) for p in (pa, pb)] == [2, 2]  # one unasked: the repair
        await a.services.store.join(quiz_id, "x", "X", "c-x")  # a change: one more frame
        await asyncio.sleep(2 * TICK_S)
    for player in (pa, pb):
        (_, repair) = player.of("snapshot")[-1]
        assert player.applied()[-1]["seq"] > repair["atSeq"]  # relaying again, with no gap


async def test_each_node_sends_rank_update_to_its_own_players(redis_url: str, quiz_id: str) -> None:
    async with cluster(redis_url, quiz_id, full_list_max=3, top_n=2) as (a, b):
        store = a.services.store
        for user in ("s1", "s2", "s3"):  # ahead of any single answer
            await store.join(quiz_id, user, user, f"c-{user}")
            for i in (0, 1):
                await store.serve_next(quiz_id, user, i, f"c-{user}")
                choice = QUESTIONS[i].correct_choice
                await store.apply_answer(quiz_id, user, i, choice, str(uuid.uuid4()), f"c-{user}")
        (pa, _), (pb, _) = await a.player(quiz_id), await b.player(quiz_id)
        await asyncio.sleep(2 * TICK_S)
        await pb.answer(0)  # pb moves to rank 4, pa shifts to rank 5
        await asyncio.sleep(1.5)  # a shifted rank goes out at most once a second
    (_, scored), *_ = [u for u in pb.of("rank_update") if u[1]["rank"] == 4]
    assert scored["atSeq"] in {f["seq"] for _, f in pb.of("leaderboard")}  # from that frame's ranks
    assert pa.of("rank_update")[-1][1]["rank"] == 5  # node A's own read


async def test_a_player_who_moves_to_the_other_node_within_the_grace_keeps_presence(
    redis_url: str, quiz_id: str
) -> None:
    async with cluster(redis_url, quiz_id, grace_ms=1_000) as (a, b):
        (moving, token), (watcher, _) = await a.player(quiz_id), await b.player(quiz_id)
        await asyncio.sleep(2 * TICK_S)
        await moving.ws.close()
        left = time.monotonic()
        await asyncio.sleep(TICK_S)
        moved = await b.rejoin(quiz_id, moving.user_id, token)
        await asyncio.sleep(1.2)  # past the grace of the socket on A
        await watcher.answer(0)
        await asyncio.sleep(2 * TICK_S)
    frames = [(t, f) for t, f in watcher.of("leaderboard") if f["onlineCount"] == 2]
    later = watcher.of("leaderboard")[watcher.of("leaderboard").index(frames[0]) :]
    assert {(f["playerCount"], f["onlineCount"]) for _, f in later} == {(2, 2)}
    assert later[-1][0] > left + 1.0  # a frame after the grace ran out
    assert moved.applied()[-1]["onlineCount"] == 2
