# AI-ASSISTED: starts a fresh 60-minute run of a bank quiz through the mock admin API.
"""Start a new quiz from the question bank and print its ID and player URL.

The quiz ID is the bank quiz's ID and a random run code (``VOCAB-42-7K3Q``), so every call opens
a quiz with a full window, whatever earlier runs left behind. It runs in the API image
(``docker compose run --rm seed``, which ``make new-quiz`` and ``make demo`` use), so it needs no
package beyond the service's own.
"""

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

from quiz.adapters.http.models import LIMIT_MS

# Upper-case letters and digits that cannot be read as one another (no 0/O, no 1/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4
ATTEMPTS = 5  # a code already taken (HTTP 409) is drawn again


def run_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def create_quiz(api_url: str, token: str, bank_id: str, code: Callable[[], str] = run_code) -> str:
    """POST /admin/quizzes with a new run ID; return the ID of the quiz it started."""
    for _ in range(ATTEMPTS):
        quiz_id = f"{bank_id}-{code()}"
        # The longest window the admin API accepts.
        body = json.dumps({"quizId": quiz_id, "windowMs": LIMIT_MS}).encode()
        request = urllib.request.Request(  # noqa: S310 - the URL is the operator's own API
            f"{api_url}/admin/quizzes",
            data=body,
            headers={"Content-Type": "application/json", "X-Admin-Token": token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10):  # noqa: S310
                return quiz_id
        except urllib.error.HTTPError as error:
            if error.code != 409:  # noqa: PLR2004 - the run ID exists
                detail = error.read().decode(errors="replace")
                msg = f"POST /admin/quizzes {quiz_id}: HTTP {error.code} {detail}"
                raise RuntimeError(msg) from None
    msg = f"no free run code for {bank_id} after {ATTEMPTS} attempts"
    raise RuntimeError(msg)


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    cli.add_argument("--bank-id", default="VOCAB-42", help="the bank quiz to play")
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
    try:
        quiz_id = create_quiz(args.api_url.rstrip("/"), token, args.bank_id)
    except (RuntimeError, urllib.error.URLError, OSError) as error:
        print(f"{error}\nIs the stack up? make demo starts it.", file=sys.stderr)
        return 1
    print(f"Quiz ID:    {quiz_id} (open for {LIMIT_MS // 60_000} min)")
    print(f"Player URL: {args.public_url.rstrip('/')}/q/{quiz_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
