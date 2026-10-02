# AI-ASSISTED: starts a fresh 60-minute run of a bank quiz, or ends a quiz, through the admin API.
"""Start a new quiz from the question bank and print its ID and player URL, or end a quiz.

The new quiz plays the bank quiz (``bankQuizId``) under its own ID: the bank quiz's ID and a random
run code (``VOCAB-42-7K3Q``), so every call opens a quiz with a full window, whatever earlier runs
left behind. ``--end`` ends a quiz as the mock host, so every player sees the final results. It
runs in the API image (``docker compose run --rm seed``, which ``make new-quiz``, ``make demo``
and ``make demo-end`` use), so it needs no package beyond the service's own.
"""

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from quiz.adapters.http.models import LIMIT_MS
from quiz.adapters.http.routes import QUIZ_ID

# Upper-case letters and digits that cannot be read as one another (no 0/O, no 1/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4
ATTEMPTS = 5  # a code already taken (HTTP 409) is drawn again
QUIZ_ID_MAX = 16  # the longest ID that QUIZ_ID matches


def run_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def run_id(bank_id: str, code: str) -> str:
    """The bank quiz's ID and the run code, the ID cut short to keep the whole a valid quiz ID."""
    return f"{bank_id[: QUIZ_ID_MAX - len(code) - 1]}-{code}"


def _post(api_url: str, token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - the URL is the operator's own API
        f"{api_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Admin-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as reply:  # noqa: S310
        return dict(json.loads(reply.read()))


def _refused(error: urllib.error.HTTPError, what: str) -> RuntimeError:
    detail = error.read().decode(errors="replace")
    return RuntimeError(f"{what}: HTTP {error.code} {detail}")


def create_quiz(api_url: str, token: str, bank_id: str, code: Callable[[], str] = run_code) -> str:
    """POST /admin/quizzes with a new run ID; return the ID of the quiz it started."""
    for _ in range(ATTEMPTS):
        quiz_id = run_id(bank_id, code())
        # The longest window the admin API accepts.
        body = {"quizId": quiz_id, "bankQuizId": bank_id, "windowMs": LIMIT_MS}
        try:
            _post(api_url, token, "/admin/quizzes", body)
        except urllib.error.HTTPError as error:
            with error:  # the reply body is a file to close
                if error.code != 409:  # noqa: PLR2004 - the run ID exists
                    raise _refused(error, f"POST /admin/quizzes {quiz_id}") from None
        else:
            return quiz_id
    msg = f"no free run code for {bank_id} after {ATTEMPTS} attempts"
    raise RuntimeError(msg)


def end_quiz(api_url: str, token: str, quiz_id: str) -> None:
    """POST /admin/quizzes/{quiz_id}/end: the host's "end now"."""
    path = f"/admin/quizzes/{quiz_id}/end"
    try:
        _post(api_url, token, path, {})
    except urllib.error.HTTPError as error:
        with error:
            raise _refused(error, f"POST {path}") from None


def quiz_id_arg(value: str) -> str:
    if not QUIZ_ID.fullmatch(value):
        msg = f"not a quiz ID (3-16 of A-Z, 0-9 and -): {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return value


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    cli.add_argument(
        "--bank-id", default="VOCAB-42", type=quiz_id_arg, help="the bank quiz to play"
    )
    cli.add_argument("--end", metavar="QUIZ_ID", type=quiz_id_arg, help="end this quiz instead")
    cli.add_argument(
        "--api-url",
        default=os.environ.get("SEED_API_URL", "http://nginx:8080/api"),
        help="the API's HTTP base, as this process reaches it",
    )
    port = os.environ.get("QUIZ_PORT") or "8080"
    cli.add_argument(
        "--public-url", default=f"http://localhost:{port}", help="the app's URL in a browser"
    )
    args = cli.parse_args(argv)
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print("set ADMIN_TOKEN, as the stack has it", file=sys.stderr)
        return 2
    api_url = args.api_url.rstrip("/")
    try:
        if args.end:
            end_quiz(api_url, token, args.end)
            lines = [f"Ended {args.end}: every player now sees the final results."]
        else:
            quiz_id = create_quiz(api_url, token, args.bank_id)
            lines = [
                f"Quiz ID:    {quiz_id} (open for {LIMIT_MS // 60_000} min)",
                f"Player URL: {args.public_url.rstrip('/')}/q/{quiz_id}",
                f"End it:     make demo-end ID={quiz_id}",
            ]
    except RuntimeError as error:  # the stack answered and refused
        print(error, file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"{error}\nIs the stack up? make demo starts it.", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
