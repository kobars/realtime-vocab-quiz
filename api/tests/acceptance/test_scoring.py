# AI-ASSISTED: acceptance tests for answers and scores (AC-3, AC-4), the deadline and retries.
import asyncio
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.acceptance.conftest import QuizServer


async def test_ac3_answer_result_carries_points_and_a_resync_shows_the_score(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    alice = await quiz_server.join("alice")
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)

    result = await bob.answer(0, key)
    snapshot = await alice.request("resync", lastSeq=0)

    assert (result["type"], result["correct"], result["late"]) == ("answer_result", True, False)
    assert 100 <= result["pointsAwarded"] <= 150
    assert result["score"] == result["pointsAwarded"]
    scores = {entry["userId"]: entry["score"] for entry in snapshot["entries"]}
    assert snapshot["type"] == "snapshot"
    assert scores[bob.user_id] == result["score"]
    assert snapshot["you"]["score"] == 0


async def test_ac4_points_come_from_server_time_and_client_timestamps_are_refused(
    quiz_server: QuizServer,
) -> None:
    quiz_server.require_manual_clock()
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    await quiz_server.advance(6800)

    claimed = await bob.request(
        "answer", questionIndex=0, choiceIndex=key, submissionId=str(uuid.uuid4()), sentAtMs=0
    )
    result = await bob.answer(0, key)

    assert (claimed["type"], claimed["code"]) == ("error", "INVALID_MESSAGE")
    assert bob.joined["timeLimitMs"] == 20_000
    assert (result["pointsAwarded"], result["score"]) == (133, 133)


async def test_ac4_a_late_answer_scores_zero(quiz_server: QuizServer) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    bob = await quiz_server.join("bob")
    question = await bob.request("next", questionIndex=0)
    await quiz_server.advance(question["timeLimitMs"] + quiz_server.margin_ms)

    result = await bob.answer(0, key)

    assert (result["type"], result["late"], result["pointsAwarded"]) == ("answer_result", True, 0)
    assert result["score"] == 0


async def test_ac4_retries_replay_the_result_and_a_new_submission_is_refused(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    submission = str(uuid.uuid4())

    first = await bob.answer(0, key, submission)
    again = await bob.answer(0, key, submission)
    other = await bob.answer(0, key)
    snapshot = await bob.request("resync", lastSeq=0)

    assert first["type"] == "answer_result"
    assert again == first
    assert (other["type"], other["code"]) == ("error", "ALREADY_ANSWERED")
    assert snapshot["you"]["score"] == first["score"]


async def test_ac4_concurrent_duplicate_answers_count_once(quiz_server: QuizServer) -> None:
    await quiz_server.create_quiz()
    key = await quiz_server.answer_key()
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    repeated = str(uuid.uuid4())
    submissions = [repeated, str(uuid.uuid4())] * 4

    await asyncio.gather(
        *(bob.send("answer", questionIndex=0, choiceIndex=key, submissionId=s) for s in submissions)
    )
    replies = [await bob.reply() for _ in submissions]
    snapshot = await bob.request("resync", lastSeq=0)

    results = [r for r in replies if r["type"] == "answer_result"]
    refused = [r for r in replies if r["type"] == "error"]
    assert results
    assert all(r == results[0] for r in results)
    assert {r["code"] for r in refused} <= {"ALREADY_ANSWERED"}
    assert len(results) + len(refused) == len(submissions)
    assert snapshot["you"]["score"] == results[0]["pointsAwarded"]


async def test_an_answer_after_the_deadline_is_refused_without_a_tick(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz(window_ms=60_000 if quiz_server.manual_clock else 1_500)
    bob = await quiz_server.join("bob")
    await bob.request("next", questionIndex=0)
    await quiz_server.advance(bob.joined["quizRemainingMs"] + quiz_server.margin_ms)

    result = await bob.answer(0, 0)

    assert (result["type"], result["code"]) == ("error", "QUIZ_ENDED")


async def test_a_repeated_next_returns_the_same_question_and_skips_nothing(
    quiz_server: QuizServer,
) -> None:
    await quiz_server.create_quiz()
    bob = await quiz_server.join("bob")

    first = await bob.request("next", questionIndex=0)
    again = await bob.request("next", questionIndex=0)
    jump = await bob.request("next", questionIndex=2)
    following = await bob.request("next", questionIndex=1)

    assert first["type"] == again["type"] == "question"
    assert (again["questionIndex"], again["questionId"]) == (0, first["questionId"])
    assert (jump["type"], jump["code"]) == ("error", "INVALID_STATE")
    assert (following["type"], following["questionIndex"]) == ("question", 1)
