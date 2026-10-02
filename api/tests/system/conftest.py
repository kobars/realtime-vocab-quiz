# AI-ASSISTED: the system tests' setup: the stack's URL, its quiz, players with sockets via nginx.
"""The system tests drive a running full stack through its nginx at ``STACK_URL``
(``make test-system``, which reads ``ADMIN_TOKEN`` from ``.env``). Nothing here starts a stack."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.typing import Origin, Subprotocol

from quiz.adapters.ws.endpoint import SUBPROTOCOL
from quiz.contracts.codec import encode
from quiz.contracts.messages import ClientMessage

QUIZ_ID = "BIZ-20"  # the browser specs take the bank's other two quizzes
RECEIVE_S = 5.0


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "system: tests of a running full stack at STACK_URL")


@pytest.fixture(scope="session")
def stack_url() -> str:
    url = os.environ.get("STACK_URL") or pytest.fail("set STACK_URL, e.g. http://localhost:8080")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def quiz_id(stack_url: str) -> str:
    """MOCK admin: start the quiz. A quiz left by an earlier run keeps its players and its window
    for 24 h, so the suite needs a stack that has not run it yet."""
    token = os.environ.get("ADMIN_TOKEN") or pytest.fail("set ADMIN_TOKEN, as the stack has it")
    reply = httpx.post(
        f"{stack_url}/api/admin/quizzes",
        json={"quizId": QUIZ_ID},
        headers={"X-Admin-Token": token},
        timeout=10,
    )
    if reply.status_code == httpx.codes.CONFLICT:
        restart = "`docker compose --profile full down -v`, then `up -d --wait`"
        pytest.fail(f"quiz {QUIZ_ID} exists from an earlier run: start the stack afresh: {restart}")
    reply.raise_for_status()
    return QUIZ_ID


@pytest.fixture
async def http(stack_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=stack_url, timeout=10) as client:
        yield client


@dataclass(slots=True)
class Player:
    ws: ClientConnection
    user_id: str
    node: str  # the API node behind nginx that holds this socket

    async def send(self, message: ClientMessage) -> None:
        await self.ws.send(encode(message).decode())

    async def receive(
        self, kind: str, until: Callable[[dict[str, Any]], bool] = lambda _: True
    ) -> dict[str, Any]:
        """The next message of this type that passes ``until``; the others are skipped."""
        async with asyncio.timeout(RECEIVE_S):
            while True:
                message: dict[str, Any] = json.loads(await self.ws.recv())
                if message["type"] == kind and until(message):
                    return message


type Session = tuple[str, dict[str, str]]  # userId, the Authorization header
type Socket = Callable[..., Awaitable[ClientConnection]]


@pytest.fixture
async def session(http: httpx.AsyncClient) -> Callable[[str], Awaitable[Session]]:
    async def create(name: str) -> Session:
        reply = (await http.post("/api/sessions", json={"displayName": name})).raise_for_status()
        body = reply.json()
        return body["userId"], {"Authorization": f"Bearer {body['sessionToken']}"}

    return create


@pytest.fixture
async def ticket(http: httpx.AsyncClient) -> Callable[[Session], Awaitable[str]]:
    async def issue(session: Session) -> str:
        reply = (await http.post("/api/tickets", headers=session[1])).raise_for_status()
        ticket: str = reply.json()["ticket"]
        return ticket

    return issue


@pytest.fixture
async def socket(stack_url: str) -> AsyncIterator[Socket]:
    """``await socket(ticket, origin=…, headers=…)``: an open ``/ws``, closed after the test."""
    async with AsyncExitStack() as sockets:

        async def open_(
            ticket: str, origin: str = stack_url, headers: Mapping[str, str] | None = None
        ) -> ClientConnection:
            ws_url = stack_url.replace("http", "ws", 1)
            dial = connect(
                f"{ws_url}/ws?ticket={ticket}",
                origin=Origin(origin),
                subprotocols=[Subprotocol(SUBPROTOCOL)],
                additional_headers=headers,
                compression=None,
                open_timeout=RECEIVE_S,
            )
            return await sockets.enter_async_context(dial)

        yield open_


@pytest.fixture
def player(
    session: Callable[[str], Awaitable[Session]],
    ticket: Callable[[Session], Awaitable[str]],
    socket: Socket,
) -> Callable[[str], Awaitable[Player]]:
    """``await player(name)``: a new mock user with an open socket, not yet joined."""

    async def create(name: str) -> Player:
        user = await session(name)
        ws = await socket(await ticket(user))
        assert ws.response is not None
        return Player(ws, user[0], ws.response.headers["X-Node-Id"])

    return create
