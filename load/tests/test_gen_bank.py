# AI-ASSISTED: the many-quizzes bank: generated quizzes load in the service's question bank.
from pathlib import Path

import pytest
from gen_bank import main

from quiz.adapters.mock_questions.bank import MockQuestionBank


async def plays(bank: MockQuestionBank, quiz_id: str) -> list[tuple[str, tuple[str, ...], int]]:
    questions = await bank.questions(quiz_id) or ()
    return [(q.prompt, q.choices, q.correct_choice) for q in questions]


def test_the_quizzes_load_and_their_ids_are_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--quizzes", "3", "--out", str(tmp_path)]) == 0
    assert MockQuestionBank.load(tmp_path).quiz_ids == ("LOAD-001", "LOAD-002", "LOAD-003")
    assert capsys.readouterr().out == "LOAD-001,LOAD-002,LOAD-003\n"


async def test_every_quiz_has_the_seeded_questions_under_its_own_ids(tmp_path: Path) -> None:
    main(["--quizzes", "2", "--out", str(tmp_path)])
    bank = MockQuestionBank.load(tmp_path)
    assert await plays(bank, "LOAD-002") == await plays(MockQuestionBank.load(), "VOCAB-42")
    questions = await bank.questions("LOAD-002") or ()
    assert [q.question_id for q in questions][:2] == ["load002-01", "load002-02"]


def test_a_smaller_bank_replaces_a_larger_one(tmp_path: Path) -> None:
    main(["--quizzes", "5", "--out", str(tmp_path)])
    main(["--quizzes", "2", "--out", str(tmp_path)])
    assert MockQuestionBank.load(tmp_path).quiz_ids == ("LOAD-001", "LOAD-002")


@pytest.mark.parametrize("count", ["0", "1000"])
def test_a_count_outside_the_id_range_is_refused(tmp_path: Path, count: str) -> None:
    with pytest.raises(SystemExit):
        main(["--quizzes", count, "--out", str(tmp_path)])
