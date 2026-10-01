# AI-ASSISTED: the full stack's smoke run: probes, one answered question, then a node stop.
"""Smoke-test the running compose ``full`` profile through nginx (``make smoke-full``).

It reads ``/healthz`` and ``/readyz`` inside each API node, plays one question through nginx,
then stops the node that holds the socket: within 10 s the player must be back through nginx,
resynced, with its score. The node then starts again. It takes the bots' options; without
``--admin-token`` it reads the token from api-1's environment.
"""

import asyncio
import contextlib
import json
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.typing import Origin

from bots import OPEN_TIMEOUT_S, SUBPROTOCOL, Options, create_quizzes, parse
from quiz.adapters.mock_questions import MockQuestionBank

NODES = ("api-1", "api-2")
REPLY_S, RECOVER_S, RETRY_S = 5.0, 10.0, 0.25
# Run in a node's container. GET prints the body of a local request and fails on an error
# status. SOCKETS counts the established connections to port 8000 (1F40) from another host:
# nginx keeps none idle and the healthcheck is local, so each one is a socket.
GET = (
    "import sys, urllib.request as u;"
    "print(u.urlopen('http://127.0.0.1:8000' + sys.argv[1]).read().decode())"
)
SOCKETS = (
    "rows = [r.split() for r in open('/proc/net/tcp').readlines()[1:]];"
    "print(sum(r[1].endswith(':1F40') and r[3] == '01' and r[2][:8] != '0100007F' for r in rows))"
)
Reply = dict[str, Any]


class SmokeError(Exception):
    pass


def compose(*args: str) -> str:
    command = ["docker", "compose", *args]
    done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode:
        msg = f"docker compose {args[0]}: {done.stderr.strip()}"
        raise SmokeError(msg)
    return done.stdout.strip()


def sockets_by_node() -> dict[str, int]:
    return {node: int(compose("exec", "-T", node, "python", "-c", SOCKETS)) for node in NODES}


async def request(ws: ClientConnection, kind: str, want: str, **body: Any) -> Reply:  # noqa: ANN401
    """Send one message; return the first reply of type ``want``, skipping broadcasts."""
    await ws.send(json.dumps({"v": 1, "type": kind, **body}))
    while True:
        reply: Reply = json.loads(await asyncio.wait_for(ws.recv(), REPLY_S))
        if reply["type"] == "error":
            msg = f"{kind}: {reply['code']} {reply['message']}"
            raise SmokeError(msg)
        if reply["type"] == want:
            return reply


async def join(http: httpx.AsyncClient, opts: Options) -> tuple[ClientConnection, Reply]:
    """A fresh ticket, a socket through nginx and its ``joined`` reply."""
    ticket = (await http.post("/tickets")).raise_for_status().json()["ticket"]
    url, origin = f"{opts.ws_url}?ticket={ticket}", Origin(opts.origin)
    ws = await connect(url, origin=origin, subprotocols=[SUBPROTOCOL], open_timeout=OPEN_TIMEOUT_S)
    return ws, await request(ws, "join", "joined", quizId=opts.quiz_ids[0], displayName="smoke")


async def recover(
    ws: ClientConnection, http: httpx.AsyncClient, opts: Options, seq: int
) -> tuple[Reply, Reply]:
    """Wait for the socket to drop, then rejoin; the ``joined`` and the resync's ``snapshot``."""
    with contextlib.suppress(ConnectionClosed):
        while True:
            await ws.recv()
    while True:
        try:
            ws, joined = await join(http, opts)
        except OSError, WebSocketException, httpx.HTTPError:  # the stopped node: try again
            await asyncio.sleep(RETRY_S)
            continue
        async with ws:
            return joined, await request(ws, "resync", "snapshot", lastSeq=seq)


async def smoke(opts: Options) -> None:
    for node in NODES:
        for path in ("/healthz", "/readyz"):
            print(f"{node} {path}: {compose('exec', '-T', node, 'python', '-c', GET, path)}")
    token = opts.admin_token or compose("exec", "-T", NODES[0], "printenv", "ADMIN_TOKEN")
    await create_quizzes(replace(opts, admin_token=token))
    bank = await MockQuestionBank.load().questions(opts.quiz_ids[0]) or ()
    key = {question.question_id: question.correct_choice for question in bank}
    async with httpx.AsyncClient(base_url=opts.url, timeout=REPLY_S) as http:
        session = (await http.post("/sessions", json={"displayName": "smoke"})).raise_for_status()
        http.headers["Authorization"] = f"Bearer {session.json()['sessionToken']}"
        before = sockets_by_node()
        ws, joined = await join(http, opts)
        i = joined["cursor"] + 1
        question = await request(ws, "next", "question", questionIndex=i)
        answer = {"questionIndex": i, "choiceIndex": key[question["questionId"]]}
        result = await request(
            ws, "answer", "answer_result", **answer, submissionId=str(uuid.uuid4())
        )
        seq, score = (await request(ws, "resync", "snapshot", lastSeq=0))["atSeq"], result["score"]
        print(f"joined {opts.quiz_ids[0]}: question {i} answered, total {score}")
        grown = [node for node, count in sockets_by_node().items() if count > before[node]]
        if len(grown) != 1:
            msg = f"cannot tell which node holds the socket: {grown}"
            raise SmokeError(msg)
        stopped = time.monotonic()
        stop = await asyncio.create_subprocess_exec("docker", "compose", "stop", grown[0])
        try:
            async with asyncio.timeout(RECOVER_S):
                joined, snapshot = await recover(ws, http, opts, seq)
            print(
                f"{grown[0]} stopped: back in {time.monotonic() - stopped:.1f} s, {snapshot['you']}"
            )
        except TimeoutError:
            msg = f"no resynced reconnect within {RECOVER_S:.0f} s"
            raise SmokeError(msg) from None
        finally:
            await stop.wait()
            compose("up", "--detach", "--wait", grown[0])
        if joined["score"] != score or (snapshot["you"] or {}).get("score") != score:
            msg = f"total {score} not kept: joined {joined['score']}, snapshot {snapshot['you']}"
            raise SmokeError(msg)


def main(argv: list[str] | None = None) -> int:
    try:
        asyncio.run(smoke(parse(argv)))
    except (SmokeError, RuntimeError, OSError, WebSocketException, httpx.HTTPError) as error:
        print(f"smoke failed: {error}", file=sys.stderr)
        return 1
    print("smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
