# AI-ASSISTED: the quiz lifecycle end to end over the gateway: finish, the deadline and host ends,
# quiz_ended with each player's final rank, late joiners and joins after the end.
"""The gateway in process, on the memory store with a manual quiz clock; real-time ticks."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from starlette.testclient import TestClient

from quiz.config import Settings
from quiz.main import create_app, services_of

Msg = dict[str, Any]
TOKEN = {"X-Admin-Token": "lifecycle-test-token"}
ORIGIN, QUIZ, WINDOW_MS, LIMIT_MS = "http://localhost:8080", "VOCAB-42", 60_000, 20_000
BROADCASTS = frozenset({"leaderboard", "quiz_ended", "rank_update"})


class Quiz:
    def __init__(self, client: TestClient, now: list[int]) -> None:
        assert client.portal is not None
        self.client, self.now, self.portal = client, now, client.portal
        services = services_of(client.app)  # type: ignore[arg-type]
        self.store, self.tick_ms = services.store, services.store.limits.tick_ms
        questions = self.portal.call(services.bank.questions, QUIZ)
        assert questions is not None
        self.key = [q.correct_choice for q in questions]

    def connect(self, name: str) -> Any:  # noqa: ANN401 - Starlette's WebSocketTestSession
        session = self.client.post("/sessions", json={"displayName": name}).json()
        bearer = {"Authorization": f"Bearer {session['sessionToken']}"}
        ticket = self.client.post("/tickets", headers=bearer).json()["ticket"]
        url = f"/ws?ticket={ticket}"
        return self.client.websocket_connect(url, ["quiz.v1"], headers={"origin": ORIGIN})

    def end_by_host(self) -> Msg:
        return dict(self.client.post(f"/admin/quizzes/{QUIZ}/end", headers=TOKEN).json())

    def seed(self, count: int) -> None:
        """Players who joined straight through the store, with no socket of their own."""
        for i in range(count):
            self.portal.call(self.store.join, QUIZ, f"seed-{i:03}", f"Seed {i}", f"c-{i}")


@contextmanager
def open_quiz() -> Iterator[Quiz]:
    now = [1_800_000_000_000]
    base = {"store": "memory", "admin_mock": True, "admin_token": TOKEN["X-Admin-Token"]}
    app = create_app(Settings.model_validate(base), clock=lambda: now[0])
    with TestClient(app) as client:
        body = {"quizId": QUIZ, "timeLimitMs": LIMIT_MS, "windowMs": WINDOW_MS}
        assert client.post("/admin/quizzes", json=body, headers=TOKEN).status_code == 201
        yield Quiz(client, now)


def until(ws: Any, match: Callable[[Msg], bool]) -> Msg:  # noqa: ANN401
    while not match(msg := cast("Msg", ws.receive_json())):
        pass
    return msg


def request(ws: Any, kind: str, **fields: object) -> Msg:  # noqa: ANN401
    """Send one request and return its reply; broadcasts that arrive first are skipped."""
    ws.send_json({"v": 1, "type": kind, **fields})
    return until(ws, lambda m: m["type"] not in BROADCASTS)


def answer(ws: Any, index: int, choice: int) -> Msg:  # noqa: ANN401
    submission = f"00000000-0000-4000-8000-{index:012}"
    return request(ws, "answer", questionIndex=index, choiceIndex=choice, submissionId=submission)


def ended(ws: Any) -> Msg:  # noqa: ANN401
    return until(ws, lambda m: m["type"] == "quiz_ended")


def test_a_finished_player_watches_the_board_until_the_deadline_brings_its_final_rank() -> None:
    with open_quiz() as quiz, quiz.connect("Ann") as ann, quiz.connect("Bob") as bob:
        assert request(ann, "join", quizId=QUIZ, displayName="Ann")["type"] == "joined"
        quiz.now[0] += 1  # at 0 points Ann ranks above Bob, who reached 0 later
        assert request(bob, "join", quizId=QUIZ, displayName="Bob")["type"] == "joined"
        request(ann, "next", questionIndex=0)
        assert answer(ann, 0, (quiz.key[0] + 1) % 4)["pointsAwarded"] == 0
        finished = request(ann, "next", questionIndex=len(quiz.key))
        assert finished == {
            "v": 1, "type": "finished", "atSeq": finished["atSeq"], "score": 0, "rank": 1,
            "playerCount": 2,
        }  # fmt: skip
        request(bob, "next", questionIndex=0)
        assert answer(bob, 0, quiz.key[0])["pointsAwarded"] == 150
        quiz.now[0] += quiz.tick_ms  # the memory store's tick token runs on the quiz clock
        board = until(ann, lambda m: m["type"] == "leaderboard" and m["entries"][0]["score"])
        assert [e["displayName"] for e in board["entries"]] == ["Bob", "Ann"]

        quiz.now[0] += WINDOW_MS  # the tick finds the deadline passed and runs end_quiz
        final = ended(ann)
        assert (final["you"], final["playerCount"]) == ({"rank": 2, "score": 0}, 2)
        assert ended(bob)["you"] == {"rank": 1, "score": 150}

        refused = answer(bob, 1, quiz.key[1])
        assert (refused["type"], refused["code"]) == ("error", "QUIZ_ENDED")
        assert request(bob, "next", questionIndex=1)["code"] == "QUIZ_ENDED"
        page = request(ann, "get_leaderboard", offset=0, limit=200)  # the socket stays open
        assert (page["final"], page["atSeq"]) == (True, final["seq"])
        assert [e["displayName"] for e in page["entries"]] == ["Bob", "Ann"]


def test_quiz_ended_carries_the_top_50_and_the_own_rank_outside_them() -> None:
    with open_quiz() as quiz, quiz.connect("Ann") as ann:
        quiz.seed(60)
        quiz.now[0] += 1  # Ann reaches 0 points after every seeded player: rank 61
        request(ann, "join", quizId=QUIZ, displayName="Ann")
        quiz.now[0] += WINDOW_MS
        final = ended(ann)
        assert (len(final["entries"]), final["playerCount"]) == (50, 61)
        assert final["you"] == {"rank": 61, "score": 0}


def test_the_host_end_reaches_every_socket_and_a_second_call_changes_nothing() -> None:
    with open_quiz() as quiz, quiz.connect("Ann") as ann, quiz.connect("Bob") as bob:
        request(ann, "join", quizId=QUIZ, displayName="Ann")
        quiz.now[0] += 1  # at 0 points Ann ranks above Bob, who reached 0 later
        request(bob, "join", quizId=QUIZ, displayName="Bob")
        first, again = (quiz.end_by_host() for _ in range(2))
        assert first == again == {"quizId": QUIZ, "status": "ended", "endSeq": first["endSeq"]}
        for ws, rank in ((ann, 1), (bob, 2)):
            final = ended(ws)
            assert (final["seq"], final["you"]) == (first["endSeq"], {"rank": rank, "score": 0})
            assert request(ws, "next", questionIndex=0)["code"] == "QUIZ_ENDED"


def test_a_late_joiner_plays_until_the_deadline_and_a_join_after_it_is_read_only() -> None:
    with open_quiz() as quiz, quiz.connect("Cara") as cara, quiz.connect("Dan") as dan:
        quiz.now[0] += WINDOW_MS - 10_000
        joined = request(cara, "join", quizId=QUIZ, displayName="Cara")
        assert (joined["quizRemainingMs"], joined["cursor"]) == (10_000, -1)
        assert request(cara, "next", questionIndex=0)["remainingMs"] == 10_000  # to the deadline
        quiz.now[0] += 1_000
        assert answer(cara, 0, quiz.key[0])["pointsAwarded"] == 147  # the full T applies

        quiz.now[0] += 9_000  # the deadline: the tick or this join, whichever comes first, ends it
        dan.send_json({"v": 1, "type": "join", "quizId": QUIZ, "displayName": "Dan"})
        snapshot = until(dan, lambda m: m["type"] == "snapshot")
        assert (snapshot["status"], snapshot["you"]) == ("ended", None)
        assert [e["displayName"] for e in snapshot["entries"]] == ["Cara"]
        error = until(dan, lambda m: m["type"] == "error")
        assert (error["code"], error["requestType"]) == ("QUIZ_ENDED", "join")
        assert ended(cara)["you"] == {"rank": 1, "score": 147}
