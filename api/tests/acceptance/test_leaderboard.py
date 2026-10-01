# AI-ASSISTED: acceptance tests for the standings (AC-5) and the live leaderboard broadcast (AC-6).
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.acceptance.conftest import Msg, QuizServer


def assert_ranked(entries: list[Msg], player_count: int) -> None:
    assert [e["rank"] for e in entries] == list(range(1, player_count + 1))
    assert len({e["userId"] for e in entries}) == player_count
    assert [e["score"] for e in entries] == sorted((e["score"] for e in entries), reverse=True)


async def test_ac5_standings_order_by_score_then_reach_time_then_user_id(
    quiz_server: QuizServer,
) -> None:
    quiz_server.require_manual_clock()
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    tied = [await quiz_server.join(name) for name in ("dave", "erin", "fay")]
    await quiz_server.advance(1000)
    zed = await quiz_server.join("zed")
    alice = await quiz_server.join("alice")
    bob = await quiz_server.join("bob")
    await alice.request("next", questionIndex=0)
    await quiz_server.advance(1000)
    await bob.request("next", questionIndex=0)
    first = await alice.answer(0, key)  # elapsed 1000 ms, reached first
    await quiz_server.advance(1000)
    second = await bob.answer(0, key)  # elapsed 1000 ms, the same score, reached later
    await tied[0].request("next", questionIndex=0)
    wrong = await tied[0].answer(0, (key + 1) % 4)  # 0 points keep the join time as reach time

    snapshot = await zed.request("resync", lastSeq=0)

    assert first["score"] == second["score"] == 147
    assert wrong["pointsAwarded"] == 0
    entries = snapshot["entries"]
    assert_ranked(entries, snapshot["playerCount"])
    assert snapshot["playerCount"] == 7  # the probe player is listed too
    tied.sort(key=lambda p: p.user_id)  # same score, same reach time: by userId
    expected = [p.user_id for p in [alice, bob, *tied, zed]]
    assert [e["userId"] for e in entries if e["userId"] in expected] == expected


async def test_ac5_pages_stitch_into_the_full_standings_above_200_players(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    players = await quiz_server.join_many(205)

    first = await players[0].request("get_leaderboard", offset=0, limit=200)
    rest = await players[0].request("get_leaderboard", offset=200, limit=200)

    assert (first["type"], first["offset"], rest["offset"]) == ("leaderboard_page", 0, 200)
    assert first["playerCount"] == rest["playerCount"] == 205
    entries = first["entries"] + rest["entries"]
    assert_ranked(entries, 205)
    assert {e["userId"] for e in entries} == {p.user_id for p in players}


async def test_ac6_leaderboard_broadcast_follows_an_accepted_answer_within_500_ms(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    alice = await quiz_server.join("alice")
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    loop = asyncio.get_running_loop()

    sent = loop.time()
    result = await bob.answer(0, key)

    def shows_bob_score(msg: Msg) -> bool:
        rows = msg["entries"] if msg["type"] == "leaderboard" else []
        return any(r["userId"] == bob.user_id and r["score"] == result["score"] for r in rows)

    frame = await alice.take(shows_bob_score, within_s=2.0)
    assert result["pointsAwarded"] > 0
    assert frame["seq"] >= 1
    assert loop.time() - sent <= 0.5
