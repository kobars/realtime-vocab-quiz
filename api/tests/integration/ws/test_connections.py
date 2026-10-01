# AI-ASSISTED: slow clients, session replacement, sender edge cases, leave grace and heartbeat.
import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, cast

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from websockets.sync.client import connect as ws_connect
from websockets.typing import Origin, Subprotocol

from quiz.adapters.memory import MemoryStore
from quiz.adapters.ws.heartbeat import server_config
from quiz.adapters.ws.limits import RateLimiter
from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.adapters.ws.session import Deps, serve
from quiz.app.service import Connection, Outcome, QuizService
from quiz.config import KIB, Settings
from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.domain.session import Question
from quiz.main import create_app, services_of
from quiz.ports.store import Store

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
    senders = [sender_of(dead, 0.1), sender_of(draining), sender_of(fast)]
    registry = Registry(cast("Store", None), 10_000)
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


async def test_a_failed_leave_is_logged_and_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    class Down:
        async def leave(self, *_: str) -> bool:
            msg = "redis is down"
            raise ConnectionError(msg)

    registry = Registry(cast("Store", Down()), 1)
    conn = Connection("c0", "u0", "VOCAB-42")
    registry.bind(conn, sender_of(Socket()))
    registry.drop(conn)
    await asyncio.sleep(0.05)
    assert "the leave of a closed connection failed" in caplog.text


async def grace_registry() -> tuple[Registry, MemoryStore, list[int]]:  # a 10 ms grace
    now = [0]
    store = MemoryStore(lambda: now[0])
    create = partial(store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
    await create("VOCAB-42", (Question("q0", 1),))
    return Registry(store, 10), store, now


async def online(store: MemoryStore) -> int:
    return (await store.snapshot("VOCAB-42", None)).online_count


async def test_a_replaced_socket_that_drops_last_keeps_the_newer_sockets_leave() -> None:
    registry, store, _ = await grace_registry()
    old, new = Connection("c-old", "u0", "VOCAB-42"), Connection("c-new", "u0", "VOCAB-42")
    for conn in (old, new):
        await store.join("VOCAB-42", "u0", "Ann", conn.conn_id)
        registry.bind(conn, sender_of(Socket()))
    registry.drop(new)
    registry.drop(old)  # its presence was taken over: it must not cancel the newer timer
    await asyncio.sleep(0.05)
    assert await online(store) == 0


async def test_a_read_only_join_keeps_the_pending_leave() -> None:
    registry, store, now = await grace_registry()
    first = Connection("c-a", "u0", "VOCAB-42")
    await store.join("VOCAB-42", "u0", "Ann", first.conn_id)
    registry.bind(first, sender_of(Socket()))
    registry.drop(first)
    now[0] = 60_000  # the quiz has ended: the next join is read-only and writes no presence
    registry.bind(Connection("c-b", "u0", "VOCAB-42", read_only=True), sender_of(Socket()))
    await asyncio.sleep(0.05)
    assert await online(store) == 0


def tickets(client: TestClient, count: int) -> list[str | None]:  # all for one user
    store = services_of(client.app).tickets  # type: ignore[arg-type]
    _, token = client.portal.call(store.create_session, "Ann")  # type: ignore[union-attr]
    return [client.portal.call(store.issue_ticket, token) for _ in range(count)]  # type: ignore[union-attr]


@contextmanager
def quiz_client(**settings: Any) -> Iterator[TestClient]:  # noqa: ANN401
    with TestClient(create_app(Settings(**settings))) as client:
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


def test_a_drop_leaves_after_the_grace_unless_the_player_comes_back() -> None:
    calls: list[tuple[str, str, bool]] = []
    with quiz_client(grace_ms=200) as client:
        store = services_of(client.app).store  # type: ignore[arg-type]
        leave = store.leave

        async def spy(*args: str) -> bool:
            left = await leave(*args)
            calls.append((args[0], args[1], left))
            return left

        store.leave = spy  # type: ignore[assignment,method-assign]
        issued, user_id = tickets(client, 2), ""
        for ticket in issued:  # the second join comes within the grace of the first socket
            with open_ws(client, ticket) as ws:
                ws.send_json(JOIN)
                user_id = ws.receive_json()["userId"]
        time.sleep(0.1)
        assert calls == []
        time.sleep(0.3)
    assert calls == [("VOCAB-42", user_id, True)]  # only the second socket's, which is present


@contextmanager
def served(app: FastAPI, settings: Settings) -> Iterator[int]:  # a live server's port
    server = uvicorn.Server(server_config(app, settings, "127.0.0.1", 0))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:  # a failed lifespan returns from startup without setting it
            assert thread.is_alive(), "the server stopped during startup"
            assert time.monotonic() < deadline, "the server did not start within 5 s"
            time.sleep(0.01)
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(5)


def test_the_server_pings_and_drops_a_socket_that_never_pongs() -> None:
    settings = Settings(heartbeat_ms=200)
    app = create_app(settings)
    with served(app, settings) as port:
        tickets_ = services_of(app).tickets
        _, token = asyncio.run(tickets_.create_session("Ann"))
        first, second = (asyncio.run(tickets_.issue_ticket(token)) for _ in range(2))
        silent = socket.create_connection(("127.0.0.1", port), timeout=3)
        silent.sendall(
            f"GET /ws?ticket={first} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Protocol: quiz.v1\r\nOrigin: {ORIGIN}\r\n\r\n".encode()
        )
        url = f"ws://127.0.0.1:{port}/ws?ticket={second}"
        with ws_connect(url, subprotocols=[Subprotocol("quiz.v1")], origin=Origin(ORIGIN)) as alive:
            start, received = time.monotonic(), b""
            while chunk := silent.recv(4096):  # the server closes it: recv returns b""
                received += chunk
            silent.close()
            assert time.monotonic() - start < 2
            assert received.startswith(b"HTTP/1.1 101")
            assert b"\x89" in received  # a ping frame came
            time.sleep(0.6)  # three more heartbeats: the socket that answers pings stays open
            alive.send(PING)
            assert json.loads(alive.recv())["type"] == "pong"


class BrokenSocket(Socket):  # the peer is gone: every write fails
    async def send_text(self, text: str) -> None:  # noqa: ARG002
        raise ConnectionResetError


def blob(size: int) -> bytes:  # one frame of exactly ``size`` bytes
    head, tail = b'{"type":"blob","pad":"', b'"}'
    return head + b"x" * (size - len(head) - len(tail)) + tail


async def test_the_hard_limit_closes_1013_even_when_the_frame_in_flight_fills_it() -> None:
    sock = Socket(reading=False)
    sender = sender_of(sock)
    sender.send_frame(blob(256 * KIB - 10))
    await asyncio.sleep(0)  # the writer takes it: it is in flight and blocks
    sender.send(page())  # past the hard limit; the error alone is past it too
    assert sender.close_code == 1013
    sock.reading.set()
    await asyncio.wait_for(sender.task, 1)
    assert [f.get("code") for f in sock.frames] == [None, "UNAVAILABLE"]
    assert sock.closed == 1013


async def test_a_close_before_the_writer_runs_still_ends_within_flush_s() -> None:
    dead = Socket(reading=False)
    sender = sender_of(dead, 0.1)
    sender.send(page())
    sender.close(4001)  # the writer task has not started yet
    await asyncio.wait_for(sender.task, 1)
    assert (dead.frames, dead.closed) == ([], 4001)


async def test_replacing_a_socket_whose_writer_failed_does_not_raise() -> None:
    registry = Registry(cast("Store", None), 10_000)
    conn = Connection("c0", "u0", "VOCAB-42")
    sender = sender_of(BrokenSocket())
    registry.bind(conn, sender)
    sender.send(page())
    await asyncio.wait_for(sender.task, 1)  # the write failed: the writer is gone
    registry.replace("c0")  # runs inside the newer socket's join
    registry.broadcast("VOCAB-42", board(1), leaderboard=True)
    assert sender.close_code == 4001


class Talking(Socket):  # a client that sends ``texts``, then leaves; it reads nothing
    def __init__(self, *texts: str) -> None:
        super().__init__(reading=False)
        self.inbound: list[dict[str, Any]] = [
            {"type": "websocket.receive", "text": t} for t in texts
        ]
        self.inbound.append({"type": "websocket.disconnect", "code": 1000})

    async def receive(self) -> dict[str, Any]:
        await asyncio.sleep(0)
        return self.inbound.pop(0)


class Service:  # records the messages the receive loop hands to the use cases
    def __init__(self) -> None:
        self.handled: list[m.ClientMessage] = []

    async def handle(self, conn: Connection, msg: m.ClientMessage) -> Outcome:  # noqa: ARG002
        self.handled.append(msg)
        return Outcome()


async def test_a_closing_socket_hands_no_more_frames_to_the_use_cases() -> None:
    sock, service = Talking(json.dumps(JOIN), PING), Service()
    sender = sender_of(sock, 0.1)
    sender.close(4001)  # replaced; its writer is still flushing to a client that does not read
    deps = Deps(cast("QuizService", service), Registry(cast("Store", None), 10_000), 16 * KIB)
    limiter = RateLimiter(20, 40, lambda: 0)
    code = await serve(cast("WebSocket", sock), Connection("c0", "u0"), limiter, sender, deps)
    assert (code, service.handled) == (4001, [])
