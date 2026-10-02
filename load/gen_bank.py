# AI-ASSISTED: writes the question bank of many quizzes that the many-quizzes load run plays.
"""Write ``--quizzes`` quiz files, ``LOAD-001`` and on, each with the questions of ``VOCAB-42``
under its own question IDs, into ``--out`` (default ``load/bank``) in place of the ``load-*.json``
files there (other files stay), and print the quiz IDs comma-separated for the swarm's
``--quiz-ids``. The API nodes read the folder when ``load/compose.bank.yaml`` mounts it over
their bank."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from quiz.adapters.mock_questions.bank import DATA

SOURCE = DATA / "vocab-42.json"
OUT = Path(__file__).parent / "bank"
MAX_QUIZZES = 999  # three digits keep the IDs in file order


def quiz(number: int, source: dict[str, Any]) -> dict[str, Any]:
    """Quiz ``number``: the bank names question n of quiz ``LOAD-007`` ``load007-0n``."""
    quiz_id = f"LOAD-{number:03d}"
    prefix = quiz_id.lower().replace("-", "")
    questions = [
        q | {"id": f"{prefix}-{n:02d}"} for n, q in enumerate(source["questions"], start=1)
    ]
    return {"quiz_id": quiz_id, "title": f"Load quiz {number}", "questions": questions}


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    cli.add_argument("--quizzes", type=int, default=500, help=f"quizzes to write, 1..{MAX_QUIZZES}")
    cli.add_argument("--out", type=Path, default=OUT, help="the bank folder")
    a = cli.parse_args(argv)
    if not 1 <= a.quizzes <= MAX_QUIZZES:
        cli.error(f"--quizzes must be 1..{MAX_QUIZZES}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("load-*.json"):  # a smaller bank must not keep an earlier run's quizzes
        old.unlink()
    quizzes = [quiz(n, source) for n in range(1, a.quizzes + 1)]
    for q in quizzes:
        path = a.out / f"{q['quiz_id'].lower()}.json"
        path.write_text(json.dumps(q, indent=2) + "\n", encoding="utf-8")
    print(",".join(q["quiz_id"] for q in quizzes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
