# AI-ASSISTED: slow clients are conflated, then closed with 1013; a second socket closes the first.
import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, cast

from fastapi import WebSocket
from starlette.testclient import TestClient

from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.app.service import Connection
from quiz.config import KIB, Settings
from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.domain.session import Question
from quiz.main import create_app, services_of

ORIGIN, PING = "http://localhost:8080", '{"v":1,"type":"ping"}'
ROWS = [
    m.Entry(rank=i, userId=f"u{i:03}", displayName=f"Player {i}", score=150) for i in range(1, 201)
]
JOIN = {"v": 1, "type": "join", "quizId": "VOCAB-42", "displayName": "Ann"}


class Socket:  # a client that reads nothing until ``reading`` is set
    def __init__(self, *, reading: bool = True) -> None:
        self.frames: list[dict[str, Any]] = []
        self.reading, self.closed = asyncio.Event(), 0
        if reading:
            self.reading.set()

    async def send_text(self, text: str) -> None:
        await self.reading.wait()
        self.frames.append(json.loads(text))

    async def close(self, code: int) -> None:
        self.closed = code


def board(seq: int) -> bytes:
    return encode(
        m.Leaderboard(seq=seq, rebase=False, playerCount=200, onlineCount=200, entries=ROWS)
    )


def page() -> m.LeaderboardPage:
    return m.LeaderboardPage(atSeq=0, offset=0, playerCount=200, final=False, entries=ROWS)


def resyncs(frames: list[dict[str, Any]]) -> int:  # the client's seq rule (protocol §3)
    last, gaps = 0, 0
    for f in (f for f in frames if f["type"] == "leaderboard"):
        gaps += f["seq"] > last + 1 and not f["rebase"]
        last = f["seq"]
    return gaps


def sender_of(sock: Socket, flush_s: float = 5.0) -> Sender:
    return Sender(cast("WebSocket", sock), 64 * KIB, 256 * KIB, flush_s)


async def test_a_conflated_client_gets_rebase_true_and_sends_no_resync() -> None:
    slow, fast = Socket(reading=False), Socket()
    senders = [sender_of(slow), sender_of(fast)]
    for seq in range(1, 31):
        for sender in senders:
            sender.send_frame(board(seq), leaderboard=True)
            if seq == 20:
                sender.send(page())  # a barrier: the held frame stays before it
        await asyncio.sleep(0)
    slow.reading.set()
    await asyncio.sleep(0.05)
    got = [(f["type"], f.get("seq"), f.get("rebase")) for f in slow.frames]
    held = [("leaderboard", 20, True), ("leaderboard_page", None, None), ("leaderboard", 30, True)]
    assert got == [("leaderboard", s, False) for s in range(1, 5)] + held
    assert resyncs(slow.frames) == 0
    assert [f.get("seq") for f in fast.frames] == [*range(1, 21), None, *range(21, 31)]


async def test_a_client_that_never_reads_is_conflated_then_closed_with_1013() -> None:
    dead, draining, fast = Socket(reading=False), Socket(reading=False), Socket()
    senders, registry = [sender_of(dead, 0.1), sender_of(draining), sender_of(fast)], Registry()
    for i, sender in enumerate(senders):
        registry.bind(Connection(f"c{i}", f"u{i}", "VOCAB-42"), sender)
    for seq in range(1, 31):
        registry.broadcast("VOCAB-42", board(seq), leaderboard=True)
        await asyncio.sleep(0)
    assert senders[0].buffered < 96 * KIB  # conflated: the leaderboards did not pile up
    for _ in range(20):  # unicasts are never dropped: they fill the queue past the hard limit
        for sender in senders:
            sender.send(page())
        await asyncio.sleep(0)
    draining.reading.set()
    await asyncio.sleep(0.3)
    assert (dead.frames, dead.closed) == ([], 1013)  # closed although it took nothing
    assert [f.get("code") for f in draining.frames][-1] == "UNAVAILABLE"
    assert draining.closed == 1013
    assert (len(fast.frames), fast.closed) == (50, 0)


def tickets(client: TestClient, count: int) -> list[str | None]:  # all for one user
    store = services_of(client.app).tickets  # type: ignore[arg-type]
    _, token = client.portal.call(store.create_session, "Ann")  # type: ignore[union-attr]
    return [client.portal.call(store.issue_ticket, token) for _ in range(count)]  # type: ignore[union-attr]


@contextmanager
def quiz_client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings())) as client:
        store = services_of(client.app).store  # type: ignore[arg-type]
        create = partial(store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
        client.portal.call(create, "VOCAB-42", (Question("q0", 1),))  # type: ignore[union-attr]
        yield client


def open_ws(client: TestClient, ticket: str | None) -> Any:  # noqa: ANN401
    return client.websocket_connect(f"/ws?ticket={ticket}", ["quiz.v1"], headers={"origin": ORIGIN})


def test_a_second_socket_of_the_user_closes_the_first_with_4001() -> None:
    with quiz_client() as client:
        first, second = tickets(client, 2)
        with open_ws(client, first) as old, open_ws(client, second) as new:
            old.send_json(JOIN)
            assert old.receive_json()["type"] == "joined"
            new.send_json(JOIN)
            assert new.receive_json()["type"] == "joined"
            assert old.receive_json()["code"] == "SESSION_REPLACED"
            assert old.receive()["code"] == 4001
            new.send_text(PING)
            assert new.receive_json()["type"] == "pong"
