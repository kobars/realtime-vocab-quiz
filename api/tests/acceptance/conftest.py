# AI-ASSISTED: black-box acceptance harness: the app on a free port, a clock, a WebSocket client.
"""Harness for the acceptance tests: they drive the server over HTTP and the WebSocket only.

The app comes from ``quiz.main:create_app``; while that factory is missing, every test skips.
The harness relies on this interface (docs/spec/protocol.md for the messages):

- ``create_app(clock=...)``: ``clock`` is a ``Callable[[], int]`` in ms, used by the memory
  store for quiz time (serve, answer, deadline, reach time). The 200 ms tick runs on real time.
  The Redis store reads Redis ``TIME`` and gets no clock. Settings come from the environment:
  ``STORE``, ``REDIS_URL``, ``PER_IP_CONN_CAP``, ``QUIZ_PORT``, ``ADMIN_MOCK``, ``ADMIN_TOKEN``.
- ``POST /sessions {displayName}`` returns ``{userId, sessionToken}``; ``POST /tickets`` with
  ``Authorization: Bearer <sessionToken>`` returns ``{ticket, expiresInMs}``.
- ``POST /admin/quizzes {quizId, timeLimitMs, windowMs}`` with the ``X-Admin-Token`` header
  creates the mock question bank's quiz of that ID: 201, or 409 when it already exists.

``ACCEPTANCE_STORE=redis`` runs the suite on the throwaway Redis at ``REDIS_URL``, which each
test flushes. Redis reads its own clock, so there the clock waits in real time, quizzes use a
300 ms time limit, timing checks use bounds, and the exact-time tests skip.
"""

import asyncio
import importlib
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import httpx
import pytest
import redis.asyncio as aioredis
import uvicorn
from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Origin, Subprotocol

Msg = dict[str, Any]
ADMIN_TOKEN = "acceptance-admin-token"  # noqa: S105 - a test value, not a secret
ORIGIN = Origin("http://localhost:8080")
BROADCASTS = frozenset({"leaderboard", "quiz_ended", "rank_update"})
STORE = os.environ.get("ACCEPTANCE_STORE", "memory")


class Player:
    """One WebSocket connection; messages that a wait skips stay in ``inbox``."""

    def __init__(self, ws: ClientConnection, user_id: str, session_token: str) -> None:
        self.ws, self.user_id, self.session_token = ws, user_id, session_token
        self.inbox: list[Msg] = []
        self.joined: Msg = {}

    async def send(self, kind: str, **fields: object) -> None:
        await self.ws.send(json.dumps({"v": 1, "type": kind, **fields}))

    async def take(self, match: Callable[[Msg], bool], within_s: float = 5.0) -> Msg:
        async with asyncio.timeout(within_s):
            while True:
                for i, msg in enumerate(self.inbox):
                    if match(msg):
                        return self.inbox.pop(i)
                self.inbox.append(json.loads(await self.ws.recv()))

    async def reply(self) -> Msg:
        """The next reply to a request: any message that is not a broadcast or a rank update."""
        return await self.take(lambda m: m["type"] not in BROADCASTS)

    async def request(self, kind: str, **fields: object) -> Msg:
        await self.send(kind, **fields)
        return await self.reply()

    async def answer(self, index: int, choice: int, submission_id: str | None = None) -> Msg:
        submission_id = submission_id or str(uuid.uuid4())
        return await self.request(
            "answer", questionIndex=index, choiceIndex=choice, submissionId=submission_id
        )


class QuizServer:
    def __init__(self) -> None:
        self.manual_clock = STORE == "memory"
        self.now_ms = 1_800_000_000_000
        self.time_limit_ms = 20_000 if self.manual_clock else 300
        self.margin_ms = 1 if self.manual_clock else 100
        self.http = httpx.AsyncClient()
        self.players: list[Player] = []

    def clock(self) -> int:
        return self.now_ms

    def require_manual_clock(self) -> None:
        if not self.manual_clock:
            pytest.skip("exact-time check: runs on the memory store with the injected clock")

    async def advance(self, ms: int) -> None:
        """Move quiz time forward: the injected clock, or a real wait on Redis."""
        if self.manual_clock:
            self.now_ms += ms
        else:
            await asyncio.sleep(ms / 1000)

    async def create_quiz(self, quiz_id: str = "VOCAB-42", window_ms: int = 600_000) -> None:
        body = {"quizId": quiz_id, "timeLimitMs": self.time_limit_ms, "windowMs": window_ms}
        resp = await self.http.post(
            "/admin/quizzes", json=body, headers={"X-Admin-Token": ADMIN_TOKEN}
        )
        assert resp.status_code in {201, 409}, resp.text

    async def connect(self, name: str, session: tuple[str, str] | None = None) -> Player:
        """Open a socket with a fresh ticket; ``session`` is ``(userId, sessionToken)``."""
        if session is None:
            resp = await self.http.post("/sessions", json={"displayName": name})
            resp.raise_for_status()
            session = (resp.json()["userId"], resp.json()["sessionToken"])
        ticket = await self.http.post("/tickets", headers={"Authorization": f"Bearer {session[1]}"})
        ticket.raise_for_status()
        ws_url = str(self.http.base_url).replace("http", "ws", 1)
        ws = await connect(
            f"{ws_url}/ws?ticket={ticket.json()['ticket']}",
            origin=ORIGIN,
            subprotocols=[Subprotocol("quiz.v1")],
        )
        self.players.append(Player(ws, *session))
        return self.players[-1]

    async def join(self, name: str, quiz_id: str = "VOCAB-42") -> Player:
        player = await self.connect(name)
        player.joined = await player.request("join", quizId=quiz_id, displayName=name)
        assert player.joined["type"] == "joined", player.joined
        return player

    async def join_many(self, count: int) -> list[Player]:
        players = await asyncio.gather(*(self.connect(f"p{i}") for i in range(count)))
        await asyncio.gather(
            *(p.send("join", quizId="VOCAB-42", displayName=f"p{i}") for i, p in enumerate(players))
        )
        for player in players:
            player.joined = await player.reply()
            assert player.joined["type"] == "joined", player.joined
        return list(players)

    async def answer_key(self) -> int:
        """Learn question 0's correct choice the way a client can: a probe player answers it."""
        probe = await self.join("probe")
        await probe.request("next", questionIndex=0)
        result = await probe.answer(0, 0)
        assert result["type"] == "answer_result", result
        return int(result["correctChoiceIndex"])


def _factory() -> Callable[..., Any]:
    try:
        module = importlib.import_module("quiz.main")
    except ModuleNotFoundError as exc:
        if exc.name != "quiz.main":
            raise
        pytest.skip("quiz.main:create_app does not exist yet")
    factory = getattr(module, "create_app", None)
    if factory is None:
        pytest.skip("quiz.main:create_app does not exist yet")
    return cast("Callable[..., Any]", factory)


@pytest.fixture
async def quiz_server(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[QuizServer]:
    create_app = _factory()
    server = QuizServer()
    env = {"STORE": STORE, "PER_IP_CONN_CAP": "1000", "QUIZ_PORT": "8080"}
    env |= {"ADMIN_MOCK": "1", "ADMIN_TOKEN": ADMIN_TOKEN}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if server.manual_clock:
        app = create_app(clock=server.clock)
    else:
        redis_url = os.environ.get("REDIS_URL") or pytest.skip(
            "ACCEPTANCE_STORE=redis needs REDIS_URL"
        )
        client = aioredis.from_url(redis_url)
        await client.flushdb()
        await client.aclose()
        app = create_app()
    runner = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", ws="websockets-sansio")
    )
    task = asyncio.create_task(runner.serve())
    while not runner.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    port = runner.servers[0].sockets[0].getsockname()[1]
    server.http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}")
    try:
        yield server
    finally:
        for player in server.players:
            await player.ws.close()
        await server.http.aclose()
        runner.should_exit = True
        await task
