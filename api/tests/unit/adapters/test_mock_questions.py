# AI-ASSISTED: the mock question bank: the seeded quizzes and the load-time validation.
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from quiz.adapters.mock_questions import MockQuestionBank, parse_quiz

GOOD: dict[str, Any] = {
    "quiz_id": "TEST-1",
    "title": "Test",
    "questions": [
        {"id": f"test1-{i:02d}", "word": f"w{i}", "choices": ["a", "b", "c", "d"], "answer": i % 4}
        for i in range(1, 11)
    ],
}


def broken(path: str, value: object) -> dict[str, Any]:
    data = copy.deepcopy(GOOD)
    *parents, last = path.split(".")
    node: Any = data
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    node[int(last) if last.isdigit() else last] = value
    return data


async def test_seeded_bank_has_three_quizzes_of_ten() -> None:
    bank = MockQuestionBank.load()
    assert len(bank.quiz_ids) >= 3
    assert "VOCAB-42" in bank.quiz_ids
    for quiz_id in bank.quiz_ids:
        questions = await bank.questions(quiz_id)
        assert questions is not None
        assert len(questions) == 10
        prefix = quiz_id.lower().replace("-", "")
        assert [q.question_id for q in questions] == [f"{prefix}-{i:02d}" for i in range(1, 11)]
        assert all(len(set(q.choices)) == 4 for q in questions)


async def test_seeded_answer_positions_follow_no_pattern() -> None:
    """Every player sees the same choice order and each answer is revealed, so the positions of
    the correct choices must not let a player predict the later ones."""
    bank = MockQuestionBank.load()
    for quiz_id in bank.quiz_ids:
        questions = await bank.questions(quiz_id)
        assert questions is not None
        answers = [q.correct_choice for q in questions]
        assert set(answers) == {0, 1, 2, 3}, quiz_id
        for period in range(1, 5):
            repeats = sum(a == b for a, b in zip(answers, answers[period:], strict=False))
            assert repeats <= (len(answers) - period) // 2, (quiz_id, period, answers)


async def test_unknown_quiz_is_none() -> None:
    assert await MockQuestionBank.load().questions("NOPE-1") is None


def test_good_quiz_parses() -> None:
    quiz_id, questions = parse_quiz(GOOD)
    assert quiz_id == "TEST-1"
    assert (questions[0].question_id, questions[0].prompt, questions[0].correct_choice) == (
        "test1-01",
        "w1",
        1,
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("quiz_id", "test-1"),  # quiz ID pattern
        ("questions.0.id", "Q42"),  # never Q<n>
        ("questions.0.id", "test1-1"),  # two digits
        ("questions.0.id", "test-1-01"),  # the quiz ID without its hyphen
        ("questions.1.id", "test1-01"),  # duplicate, out of order
        ("questions.0.choices", ["a", "b", "c"]),  # 4 choices
        ("questions.0.choices", ["a", "b", "c", "a"]),  # distinct choices
        ("questions.0.choices", ["a", "b", "c", ""]),  # no empty choice
        ("questions.0.answer", 4),  # answer index 0-3
        ("questions.0.answer", -1),
        ("questions.0.answer", "2"),  # strict: no string, bool or float as the index
        ("questions.0.answer", True),
        ("questions.0.answer", 1.0),
        ("questions.0.word", ""),
        ("questions.0.extra", 1),  # unknown field
        ("questions", []),
    ],
)
def test_bad_quiz_is_rejected(path: str, value: object) -> None:
    with pytest.raises(ValueError, match="quiz"):
        parse_quiz(broken(path, value))


def test_duplicate_quiz_ids_are_rejected(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps(GOOD))
    with pytest.raises(ValueError, match="TEST-1"):
        MockQuestionBank.load(tmp_path)


def test_bad_file_is_named(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(json.dumps(broken("questions.0.id", "Q42")))
    with pytest.raises(ValueError, match=r"bad\.json"):
        MockQuestionBank.load(tmp_path)

