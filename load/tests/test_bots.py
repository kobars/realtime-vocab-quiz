# AI-ASSISTED: the bots' frame shortcut, CLI and one swarm run against the app.
import asyncio

import pytest
import uvicorn
from pydantic import SecretStr

from bots import BOARD_HEAD, _worker, create_quizzes, parse
from quiz.config import Settings
from quiz.contracts.codec import encode_broadcast
from quiz.contracts.messages import Entry, Leaderboard
from quiz.main import create_app


def test_the_board_header_regex_reads_the_servers_encoding() -> None:
    entry = Entry(rank=1, userId="u1", displayName="Ann", score=150)
    raw = encode_broadcast(
        Leaderboard(seq=12, rebase=True, playerCount=1, onlineCount=1, entries=[entry])
    ).decode()
    head = BOARD_HEAD.match(raw)
    assert head is not None
    assert (head[1], head[2]) == ("12", "true")


def test_the_cli_checks_its_options() -> None:
    opts = parse(["--url", "https://quiz.example/api/", "--quizzes", "2", "--bots", "4"])
    assert opts.quiz_ids == ("VOCAB-42", "BIZ-20")
    assert opts.ws_url == "wss://quiz.example/ws"
    for bad in (["--quizzes", "4"], ["--procs", "11"], ["--accuracy", "1.5"]):
        with pytest.raises(SystemExit):
            parse(bad)


async def test_a_swarm_plays_whole_quizzes_against_the_app() -> None:
    app = create_app(Settings(admin_mock=True, admin_token=SecretStr("load-token")))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    opts = parse(
        [
            "--url",
            f"http://127.0.0.1:{port}",
            "--quizzes",
            "2",
            "--bots",
            "3",
            "--think-ms",
            "0",
            "--duration",
            "1",
            "--ramp",
            "0",
            "--timeout-ms",
            "300",
            "--admin-token",
            "load-token",
        ]
    )
    try:
        await create_quizzes(opts)
        rec, proc = await _worker(opts, 0)
    finally:
        server.should_exit = True
        await serving
    assert rec.counts["cohorts"] >= 3
    assert rec.counts["answers"] >= 30  # every cohort answers all ten questions
    assert len(rec.answer_ms) == rec.counts["answers"]
    for failure in ("answer_timeout", "answer_missing", "failed_opens", "reconnects"):
        assert rec.counts[failure] == 0
    assert proc["cpu_pct"] >= 0
