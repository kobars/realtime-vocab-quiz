# AI-ASSISTED: the composed stack through nginx: play, cross-node delivery and the edge's rules.
import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from websockets.exceptions import InvalidStatus

from quiz.adapters.mock_questions import MockQuestionBank
from quiz.config import Settings
from quiz.contracts.messages import Answer, Join, Next

if TYPE_CHECKING:
    from tests.system.conftest import Player, Session, Socket

pytestmark = pytest.mark.system

REPO = Path(__file__).resolve().parents[3]
CROSS_NODE_S = 0.5  # answer accepted on one node -> leaderboard frame on the other
NODE_TRIES = 6  # nginx alternates the nodes, but HTTP requests share its round-robin
CAP_SOCKETS_MAX = 201  # sockets the cap test may hold at once: under a 256 open-file limit


async def correct_choice(quiz_id: str, index: int) -> int:
    questions = await MockQuestionBank.load().questions(quiz_id)
    assert questions is not None
    return questions[index].correct_choice


async def answer_first(p: Player, quiz_id: str) -> dict[str, object]:
    """Join, open question 0 and answer it correctly; return the ``answer_result``."""
    await p.send(Join(quizId=quiz_id, displayName="system"))
    await p.receive("joined")
    await p.send(Next(questionIndex=0))
    await p.receive("question")
    choice = await correct_choice(quiz_id, 0)
    await p.send(Answer(questionIndex=0, choiceIndex=choice, submissionId=str(uuid.uuid4())))
    return await p.receive("answer_result")


def security_headers() -> dict[str, str]:
    """Each ``add_header Name "value" always;`` line of the web image's snippet."""
    snippet = (REPO / "web" / "security-headers.conf").read_text(encoding="utf-8")
    pairs = re.findall(r'^add_header (\S+) "(.*)" always;$', snippet, re.MULTILINE)
    assert pairs
    return dict(pairs)


async def test_a_player_joins_and_answers(
    player: Callable[[str], Awaitable[Player]], quiz_id: str
) -> None:
    result = await answer_first(await player("Ann"), quiz_id)
    assert result["correct"] is True
    assert 100 <= result["pointsAwarded"] <= 150  # type: ignore[operator]


async def test_a_score_on_one_node_reaches_a_socket_on_the_other(
    player: Callable[[str], Awaitable[Player]], quiz_id: str
) -> None:
    scorer = await player("Bea")
    for _ in range(NODE_TRIES):
        if (watcher := await player("Cy")).node != scorer.node:
            break
    else:
        pytest.fail(f"every socket landed on {scorer.node}")
    await watcher.send(Join(quizId=quiz_id, displayName="watcher"))
    await watcher.receive("joined")

    def shows_score(frame: dict[str, object]) -> bool:
        rows = frame["entries"]
        assert isinstance(rows, list)
        return any(row["userId"] == scorer.user_id and row["score"] > 0 for row in rows)

    async with asyncio.TaskGroup() as tasks:  # a failed answer cancels the wait
        seen = tasks.create_task(watcher.receive("leaderboard", shows_score))
        await answer_first(scorer, quiz_id)
        accepted = time.monotonic()
        await seen
    assert time.monotonic() - accepted < CROSS_NODE_S


async def test_the_upgrade_from_another_origin_gets_403(socket: Socket) -> None:
    with pytest.raises(InvalidStatus) as refused:  # the Origin is checked before the ticket
        await socket("unused", origin="http://evil.example")
    assert refused.value.response.status_code == 403


async def test_a_spoofed_x_forwarded_for_does_not_lift_the_per_ip_cap(
    session: Callable[[str], Awaitable[Session]],
    ticket: Callable[[Session], Awaitable[str]],
    socket: Socket,
) -> None:
    """nginx replaces the client's X-Forwarded-For, so every socket counts against one address
    on its node: with both nodes full, the next upgrade gets 429."""
    cap = Settings().per_ip_conn_cap  # the stack's too: make test-system exports .env
    if (attempts := 2 * cap + 1) > CAP_SOCKETS_MAX:
        pytest.skip(f"PER_IP_CONN_CAP={cap} needs {attempts} sockets to fill both nodes")
    user = await session("Dee")
    tickets = [await ticket(user) for _ in range(attempts)]  # before the sockets: no 429 between
    status = None
    for i, issued in enumerate(tickets):
        try:
            await socket(issued, headers={"X-Forwarded-For": f"203.0.113.{i % 250 + 1}"})
        except InvalidStatus as refused:
            status = refused.response.status_code
            break
    assert status == 429, f"{attempts} upgrades from one address, each with its own X-Forwarded-For"


async def test_metrics_stay_inside_the_stack(http: httpx.AsyncClient) -> None:
    assert (await http.get("/api/healthz")).status_code == 200
    assert (await http.get("/api/metrics")).status_code == 404


async def test_a_body_above_the_edge_limit_gets_413(http: httpx.AsyncClient) -> None:
    conf = (REPO / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    limit = re.search(r"client_max_body_size (\d+)k;", conf)
    assert limit is not None
    body = b"x" * (int(limit[1]) * 1024 + 1)
    reply = await http.post("/api/sessions", content=body, headers={"Content-Type": "text/plain"})
    assert reply.status_code == 413


async def test_the_edge_sends_the_security_headers(http: httpx.AsyncClient, socket: Socket) -> None:
    replies: list[Mapping[str, str]] = [(await http.get(p)).headers for p in ("/", "/api/healthz")]
    with pytest.raises(InvalidStatus) as refused:
        await socket("unused", origin="http://evil.example")
    replies.append(refused.value.response.headers)
    for headers in replies:
        assert {name: headers.get(name) for name in security_headers()} == security_headers()
