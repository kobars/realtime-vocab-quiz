# AI-ASSISTED: slow clients, session replacement, sender edge cases, leave grace and heartbeat.
import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, cast, override

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from websockets.sync.client import connect as ws_connect
from websockets.typing import Origin, Subprotocol

from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore
from quiz.adapters.ws import endpoint
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
from quiz.ports.questions import BankQuestion
from quiz.ports.store import Joined, Served, Store

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


def limiter() -> RateLimiter:
    return RateLimiter(20, 40, lambda: 0)


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
    # Each frame past the soft limit replaces every leaderboard queued since the last barrier:
    # 18 replaced 14-17, and 19, 20 queued below the limit again.
    queued = [("leaderboard", 18, True), ("leaderboard", 19, False), ("leaderboard", 20, False)]
    held = [("leaderboard_page", None, None), ("leaderboard", 30, True)]
    assert got == [("leaderboard", 1, False), *queued, *held]
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
    conn = Connection("c0", "u0", "VOCAB-42", present=True)
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


@pytest.mark.parametrize("newest_bound_first", [False, True])  # a late reply binds out of order
async def test_a_replaced_socket_that_drops_last_keeps_the_newer_sockets_leave(
    *, newest_bound_first: bool
) -> None:
    registry, store, _ = await grace_registry()
    old, new = (Connection(c, "u0", "VOCAB-42", present=True) for c in ("c-old", "c-new"))
    for conn in (old, new):
        await store.join("VOCAB-42", "u0", "Ann", conn.conn_id)
    for conn in (new, old) if newest_bound_first else (old, new):
        registry.bind(conn, sender_of(Socket()))
    registry.drop(new)
    registry.drop(old)  # its presence was taken over: it must not cancel the newer timer
    await asyncio.sleep(0.05)
    assert await online(store) == 0


async def test_a_read_only_join_keeps_the_pending_leave() -> None:
    registry, store, now = await grace_registry()
    first = Connection("c-a", "u0", "VOCAB-42", present=True)
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


def reply(ws: Any) -> dict[str, Any]:  # noqa: ANN401
    """The next message that is not a leaderboard: the tick may relay one at any time."""
    while (msg := ws.receive_json())["type"] == "leaderboard":
        pass
    return cast("dict[str, Any]", msg)


def test_a_second_socket_of_the_user_closes_the_first_with_4001() -> None:
    with quiz_client() as client:
        first, second = tickets(client, 2)
        with open_ws(client, first) as old, open_ws(client, second) as new:
            old.send_json(JOIN)
            assert reply(old)["type"] == "joined"
            new.send_json(JOIN)
            assert reply(new)["type"] == "joined"
            assert reply(old)["code"] == "SESSION_REPLACED"
            assert old.receive()["code"] == 4001
            new.send_text(PING)
            assert reply(new)["type"] == "pong"


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
    first, second = ("VOCAB-42", user_id, False), ("VOCAB-42", user_id, True)
    assert calls == [first, second]  # the second join took over: the first socket's leave is stale


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
            assert json.loads(alive.recv(timeout=2))["type"] == "pong"


class BrokenSocket(Socket):  # the peer is gone: every write fails
    @override
    async def send_text(self, text: str) -> None:
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
    assert sender.close_code == 4001


async def test_a_failed_write_leaves_only_the_queue_in_the_buffer() -> None:
    sender = sender_of(BrokenSocket())
    sender.send(page())
    await asyncio.wait_for(sender.task, 1)  # the write failed: that frame is gone
    sender.send(page())
    assert sender.buffered == len(encode(page()))


async def test_a_broadcast_past_the_hard_limit_after_a_failed_write_closes_1013() -> None:
    registry = Registry(cast("Store", None), 10_000)
    sender = sender_of(BrokenSocket())
    registry.bind(Connection("c0", "u0", "VOCAB-42"), sender)
    sender.send(page())
    await asyncio.wait_for(sender.task, 1)  # the write failed: the writer is gone
    registry.broadcast("VOCAB-42", blob(256 * KIB + 1), leaderboard=False)
    assert sender.close_code == 1013


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
    sender.send(page())
    await asyncio.sleep(0)  # the writer takes it and blocks: the client does not read
    sender.close(4001)  # replaced while its writer is still flushing
    deps = Deps(cast("QuizService", service), Registry(cast("Store", None), 10_000), 16 * KIB)
    code = await serve(cast("WebSocket", sock), Connection("c0", "u0"), limiter(), sender, deps)
    assert (code, service.handled) == (4001, [])


class Bank:  # the one question of every quiz in these tests
    async def questions(self, quiz_id: str) -> tuple[BankQuestion, ...]:  # noqa: ARG002
        return (BankQuestion("q0", "word?", ("a", "b", "c", "d"), 1),)

    async def title(self, quiz_id: str) -> str:
        return quiz_id


class Client(Socket):  # sends ``texts``, then each ``say``; it stays open
    def __init__(self, *texts: str) -> None:
        super().__init__()
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for text in texts:
            self.say(text)

    def say(self, text: str) -> None:
        self.inbound.put_nowait({"type": "websocket.receive", "text": text})

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()


async def test_a_replaced_socket_whose_join_reply_comes_last_is_closed_with_4001() -> None:
    registry, store, _ = await grace_registry()
    join, newer_joined = store.join, asyncio.Event()

    async def older_reply_last(quiz_id: str, user_id: str, name: str, conn_id: str) -> Joined:
        joined = await join(quiz_id, user_id, name, conn_id)
        if conn_id == "c-old":  # the store took this join first; its reply reaches the node last
            await newer_joined.wait()
        else:
            newer_joined.set()
        return joined

    store.join = older_reply_last  # type: ignore[assignment,method-assign]
    deps = Deps(QuizService(store, Bank(), lambda: 0), registry, 16 * KIB)
    old, new = Client(json.dumps(JOIN)), Client(json.dumps(JOIN))
    conns = {old: Connection("c-old", "u0"), new: Connection("c-new", "u0")}
    senders = {old: sender_of(old), new: sender_of(new)}

    def serving(sock: Client) -> asyncio.Task[int]:
        ws = cast("WebSocket", sock)
        return asyncio.create_task(serve(ws, conns[sock], limiter(), senders[sock], deps))

    older = serving(old)
    await asyncio.sleep(0.01)  # the older join reaches the store first
    newer = serving(new)
    try:
        await asyncio.wait({older}, timeout=1)
        assert ([f.get("code") for f in old.frames], old.closed) == (["SESSION_REPLACED"], 4001)
        assert (older.result(), [f["type"] for f in new.frames]) == (4001, ["joined"])
        registry.drop(conns[old])  # as the endpoint does once serve returns
        assert registry.senders("VOCAB-42") == [senders[new]]
    finally:
        older.cancel()
        newer.cancel()


class GatedStore(MemoryStore):  # joins pass the gate one at a time, in arrival order
    def __init__(self) -> None:
        super().__init__(lambda: 0)
        self.gate = asyncio.Lock()

    @override
    async def join(self, quiz_id: str, user_id: str, display_name: str, conn_id: str) -> Joined:
        async with self.gate:
            return await super().join(quiz_id, user_id, display_name, conn_id)


async def test_a_replaced_sockets_in_flight_join_does_not_take_the_session_back() -> None:
    store = GatedStore()
    create = partial(store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
    await create("VOCAB-42", (Question("q0", 1),))
    service = QuizService(store, Bank(), lambda: 0)
    deps = Deps(service, Registry(store, 10_000), 16 * KIB)
    old, new = Client(), Client()
    old_served, new_served = (
        asyncio.create_task(
            serve(cast("WebSocket", s), Connection(conn_id, "u1"), limiter(), sender_of(s), deps)
        )
        for s, conn_id in ((old, "c1"), (new, "c2"))
    )
    old.say(json.dumps(JOIN))
    await asyncio.sleep(0.01)
    old.reading.clear()  # its writer is still flushing when the newer join closes it
    async with store.gate:  # the newer join waits first, then the old socket's re-join
        new.say(json.dumps(JOIN))
        await asyncio.sleep(0.01)
        old.say(json.dumps(JOIN))
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    old.reading.set()
    assert await asyncio.wait_for(old_served, 1) == 4001
    assert (old.closed, new.closed, new_served.done()) == (4001, 0, False)
    assert isinstance(await store.serve_next("VOCAB-42", "u1", 0, "c2"), Served)  # c2 present
    new.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
    assert await asyncio.wait_for(new_served, 1) == 1000


async def test_a_socket_closed_during_its_committed_join_still_leaves_and_replaces() -> None:
    registry, store, _ = await grace_registry()
    await store.join("VOCAB-42", "u0", "Ann", "c2")
    other = sender_of(Socket())
    registry.bind(Connection("c2", "u0", "VOCAB-42"), other)
    sock = Talking(json.dumps(JOIN))
    sender, service = sender_of(sock, 0.1), QuizService(store, Bank(), lambda: 0)

    class Overloaded:  # the join commits while a broadcast overloads this socket and closes it
        async def handle(self, conn: Connection, msg: m.ClientMessage) -> Outcome:
            outcome = await service.handle(conn, msg)
            sender.close(1013)
            return outcome

    deps = Deps(cast("QuizService", Overloaded()), registry, 16 * KIB)
    conn = Connection("c1", "u0")
    code = await serve(cast("WebSocket", sock), conn, limiter(), sender, deps)
    registry.drop(conn)  # as the endpoint does once serve returns
    await asyncio.sleep(0.05)
    assert (code, other.close_code, await online(store)) == (1013, 4001, 0)


class Stalled(Talking):  # a transport that is not writable: the close frame never goes out
    @override
    async def close(self, code: int) -> None:
        await asyncio.Event().wait()


@pytest.mark.parametrize("drained", [True, False])
async def test_a_close_that_stalls_is_given_up_and_the_handler_ends(*, drained: bool) -> None:
    sock = Stalled()
    sender = sender_of(sock, 0.1)
    if not drained:
        sender.send(page())  # the client reads nothing: the drain runs out first
    sender.close(1013)
    deps = Deps(cast("QuizService", Service()), Registry(cast("Store", None), 10_000), 16 * KIB)
    handler = serve(cast("WebSocket", sock), Connection("c0", "u0"), limiter(), sender, deps)
    assert await asyncio.wait_for(handler, 2) == 1013


class Lagging(Socket):  # its close frame goes out a little after the drain
    @override
    async def close(self, code: int) -> None:
        await asyncio.sleep(0.07)
        await super().close(code)


async def test_a_close_frame_that_ends_just_after_the_deadline_is_still_sent() -> None:
    sock = Lagging(reading=False)
    sender = sender_of(sock, 0.2)
    sender.send(page())
    sender.close(4001)
    asyncio.get_running_loop().call_later(0.18, sock.reading.set)  # the drain ends just in time
    await asyncio.wait_for(sender.task, 2)
    assert (len(sock.frames), sock.closed) == (1, 4001)


async def test_a_present_socket_that_joins_again_after_the_end_still_leaves() -> None:
    registry, store, now = await grace_registry()
    service, conn = QuizService(store, Bank(), lambda: now[0]), Connection("c0", "u0")
    join = m.Join(quizId="VOCAB-42", displayName="Ann")
    assert [type(r) for r in (await service.handle(conn, join)).replies] == [m.Joined]
    registry.bind(conn, sender_of(Socket()))
    now[0] = 60_000  # past the deadline: the repeated join is answered read only
    replies = (await service.handle(conn, join)).replies
    assert [type(r) for r in replies] == [m.Snapshot, m.ProtocolError]
    registry.drop(conn)
    await asyncio.sleep(0.05)
    assert await online(store) == 0


async def test_a_given_up_close_keeps_the_cap_slot_until_the_transport_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(endpoint, "Sender", partial(Sender, flush_s=0.05))
    app = create_app(Settings())
    services, gateway = services_of(app), app.state.gateway
    create = partial(services.store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
    await create("VOCAB-42", (Question("q0", 1),))
    tickets = cast("MemoryTicketStore", services.tickets)
    ticket = await tickets.issue_ticket((await tickets.create_session("Ann"))[1])
    inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    inbound.put_nowait({"type": "websocket.connect"})
    for text in (json.dumps(JOIN), "x" * (16 * KIB + 1)):  # the second frame closes it with 1009
        inbound.put_nowait({"type": "websocket.receive", "text": text})

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "websocket.close":  # the peer reads nothing: it never goes out
            await asyncio.Event().wait()

    scope = {
        "type": "websocket",
        "path": "/ws",
        "query_string": f"ticket={ticket}".encode(),
        "headers": [(b"origin", ORIGIN.encode())],
        "subprotocols": ["quiz.v1"],
        "client": ("10.0.0.1", 5000),
    }
    ws = WebSocket(scope, inbound.get, send)  # type: ignore[arg-type]
    handler = asyncio.create_task(gateway.endpoint(ws))
    await asyncio.sleep(1.3)  # past flush_s and the close frame's own second: given up
    assert gateway.registry.senders("VOCAB-42") == []  # the registry lets go at the deadline
    assert (handler.done(), gateway.caps.total) == (False, 1)
    inbound.put_nowait({"type": "websocket.disconnect", "code": 1006})
    await asyncio.wait_for(handler, 1)
    assert gateway.caps.total == 0
