# AI-ASSISTED: acceptance tests for joining a quiz (AC-1, AC-2) and for a reconnect.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.acceptance.conftest import QuizServer


async def test_ac1_join_by_quiz_id_and_refuse_unknown_or_malformed_ids(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz("VOCAB-42")
    alice = await quiz_server.connect("alice")

    malformed = await alice.request("join", quizId="vocab 42!", displayName="alice")
    unknown = await alice.request("join", quizId="ZZZ-999", displayName="alice")
    joined = await alice.request("join", quizId="VOCAB-42", displayName="alice")

    assert (malformed["type"], malformed["code"]) == ("error", "INVALID_MESSAGE")
    assert (unknown["type"], unknown["code"], unknown["requestType"]) == (
        "error",
        "QUIZ_NOT_FOUND",
        "join",
    )
    assert joined["type"] == "joined"
    assert isinstance(joined["atSeq"], int)
    assert joined["atSeq"] >= 0
    assert (joined["quizId"], joined["userId"], joined["score"]) == ("VOCAB-42", alice.user_id, 0)


async def test_ac2_200_concurrent_joins_each_appear_once_in_the_standings(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    players = await quiz_server.join_many(200)

    snapshot = await players[0].request("resync", lastSeq=0)

    user_ids = [entry["userId"] for entry in snapshot["entries"]]
    assert snapshot["type"] == "snapshot"
    assert snapshot["playerCount"] == 200
    assert sorted(user_ids) == sorted(p.user_id for p in players)


async def test_reconnect_with_a_new_ticket_keeps_the_user_and_the_total(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    result = await bob.answer(0, key)
    await bob.ws.close()

    again = await quiz_server.connect("bob", session=(bob.user_id, bob.session_token))
    joined = await again.request("join", quizId="VOCAB-42", displayName="bob")

    assert result["pointsAwarded"] >= 100
    assert joined["type"] == "joined"
    assert (joined["userId"], joined["score"]) == (bob.joined["userId"], result["score"])
