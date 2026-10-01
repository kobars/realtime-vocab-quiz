# AI-ASSISTED: one bot's protocol rules: reconnect backoff, play state and latency samples.
"""What a bot does with each server message and when it sends the next one; no I/O.

Times are monotonic seconds; reported latencies are milliseconds. The bot follows the web
client: full-jitter backoff (none after close 1000, 1008 or 4001; 5 s more after 1013), one
``resync`` after each ``joined``, a resync after a ``seq`` gap, and an open answer resent with
the same ``submissionId``.
"""

import math
import random
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

OVERLOAD_WAIT_S, BACKOFF_RESET_S, RESYNC_EVERY_S = 5.0, 10.0, 1.0
NORMAL, DEAD_LINK, OVERLOAD = 1000, 1006, 1013
FINAL_CODES = frozenset({NORMAL, 1008, 4001})
REJOIN_ERRORS = frozenset({"QUESTION_NOT_OPEN", "INVALID_STATE", "ALREADY_ANSWERED", "NOT_JOINED"})


def backoff_s(attempt: int, rnd: float) -> float:
    """Full jitter: ``floor(rnd * min(10000, 250 * 2^attempt))`` ms, in seconds."""
    return math.floor(rnd * min(10_000, 250 << attempt)) / 1000


@dataclass(slots=True)
class Backoff:
    attempt: int = 0
    joined_at: float | None = None

    def closed(self, code: int, now: float, rnd: float) -> float | None:
        """The wait before the next connect, or ``None`` when the bot must not reconnect."""
        if self.joined_at is not None and now - self.joined_at >= BACKOFF_RESET_S:
            self.attempt = 0
        self.joined_at = None
        if code in FINAL_CODES:
            return None
        wait = backoff_s(self.attempt, rnd)
        self.attempt += 1
        return wait + OVERLOAD_WAIT_S if code == OVERLOAD else wait


@dataclass(slots=True)
class Recorder:
    """One process's samples. ``answer_ms``: send ``answer`` → ``answer_result``.
    ``board_ms``: ``answer_result`` with points → the first frame that shows the new total."""

    answer_ms: list[float] = field(default_factory=list)
    board_ms: list[float] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    def merge(self, other: Recorder) -> None:
        self.answer_ms += other.answer_ms
        self.board_ms += other.board_ms
        self.counts += other.counts


@dataclass(slots=True)
class BoardWait:
    """The totals one player waits to see on a ``leaderboard`` or ``rank_update``."""

    recorder: Recorder
    timeout_s: float
    pending: list[tuple[int, float]] = field(default_factory=list)  # (total, accepted at)

    def accepted(self, total: int, now: float) -> None:
        self.pending.append((total, now))

    def shown(self, total: int, now: float) -> None:
        """A frame shows ``total``: it settles every wait for that total or a lower one."""
        keep = []
        for want, since in self.pending:
            if want <= total:
                self.recorder.board_ms.append((now - since) * 1000)
            else:
                keep.append((want, since))
        self.pending = keep

    def expire(self, now: float) -> None:
        late = [p for p in self.pending if now - p[1] > self.timeout_s]
        self.recorder.counts["board_timeout"] += len(late)
        self.pending = [p for p in self.pending if now - p[1] <= self.timeout_s]

    def abandon(self) -> None:
        """The connection or the run ended first: the open waits are missing samples."""
        self.recorder.counts["board_missing"] += len(self.pending)
        self.pending = []


@dataclass(slots=True)
class Player:
    """One bot's player and its open work; it lives across the reconnects of one cohort."""

    quiz_id: str
    name: str
    rec: Recorder
    board: BoardWait
    key: dict[str, int]  # questionId -> correct choice, learned from answer_result
    deadline: float  # no new answers after it
    accuracy: float = 1.0
    user_id: str = ""
    question_id: str = ""
    answer: tuple[int, str, int] | None = None  # (question index, submissionId, choice)
    answer_due: float | None = None  # when the think time ends and the answer goes out
    sent_at: float | None = None  # the last send of the open answer
    timed: bool = False  # the open answer's first send: its reply is a latency sample
    last_seq: int | None = None
    resyncing: bool = False
    resync_at: float | None = None
    last_resync: float = -math.inf
    finished: bool = False
    ended: bool = False
    outbox: list[dict[str, Any]] = field(default_factory=list)

    def send(self, kind: str, **body: Any) -> None:  # noqa: ANN401
        self.outbox.append({"v": 1, "type": kind, **body})

    def choose(self, question_id: str) -> int:
        correct = self.key.get(question_id)
        if correct is None:
            return random.randrange(4)  # noqa: S311 - load pattern, not security
        if random.random() < self.accuracy:  # noqa: S311
            return correct
        return random.choice([c for c in range(4) if c != correct])  # noqa: S311

    def on_seq(self, seq: int, rebase: bool, now: float) -> None:  # noqa: FBT001
        if self.last_seq is None or self.resyncing:
            return
        if seq == self.last_seq + 1 or (rebase and seq > self.last_seq):
            self.last_seq = seq
        elif seq != self.last_seq:  # a gap, or the counter went back after a store restart
            self.rec.counts["seq_gaps"] += 1
            self.resync_at = now + (random.uniform(0, 0.25) if seq > self.last_seq else 0)  # noqa: S311

    def handle(self, msg: dict[str, Any], now: float, backoff: Backoff, think_s: float) -> None:  # noqa: C901, PLR0912
        kind = msg["type"]
        if kind == "joined":
            backoff.joined_at, self.user_id = now, msg["userId"]
            self.send("resync", lastSeq=self.last_seq or 0)
            self.resyncing, self.last_resync = True, now
            self.finished = msg["finished"]
            if not self.finished and now < self.deadline:
                self.send("next", questionIndex=msg["cursor"] + (0 if msg["cursorOpen"] else 1))
        elif kind == "question":
            self.question_id, index = msg["questionId"], msg["questionIndex"]
            if self.answer is not None and self.answer[0] == index:  # re-served: resend, untimed
                self.answer_due, self.timed = now, False
            else:
                self.answer = (index, str(uuid.uuid4()), self.choose(self.question_id))
                self.answer_due = now + think_s * random.uniform(0.5, 1.5)  # noqa: S311
                self.timed = True
        elif kind == "answer_result" and self.answer and msg["submissionId"] == self.answer[1]:
            if self.timed and self.sent_at is not None:
                self.rec.answer_ms.append((now - self.sent_at) * 1000)
            self.key[self.question_id] = msg["correctChoiceIndex"]
            if msg["pointsAwarded"] > 0:
                self.board.accepted(msg["score"], now)
            self.answer = self.sent_at = None
            self.timed = False
            self.rec.counts["answers"] += 1
            if now < self.deadline:
                self.send("next", questionIndex=msg["questionIndex"] + 1)
        elif kind == "finished":
            self.finished = True
        elif kind == "leaderboard":
            self.on_seq(msg["seq"], msg["rebase"], now)
            for entry in msg["entries"]:
                if entry["userId"] == self.user_id:
                    self.board.shown(entry["score"], now)
        elif kind == "rank_update":
            self.board.shown(msg["score"], now)
        elif kind == "snapshot":
            self.last_seq, self.resyncing = msg["atSeq"], False
        elif kind == "quiz_ended":
            self.ended = True
        elif kind == "error":
            self.rec.counts[f"error_{msg['code']}"] += 1
            if msg["code"] == "QUIZ_ENDED":
                self.ended = True
            elif msg["code"] in REJOIN_ERRORS:  # read the stored cursor again
                self.drop_answer()
                self.send("join", quizId=self.quiz_id, displayName=self.name)

    def due(self, now: float, timeout_s: float) -> None:
        """Send what the clock asks for: the answer after its think time, a resync, a retry."""
        if self.answer_due is not None and now >= self.answer_due and self.answer:
            index, submission, choice = self.answer
            self.send("answer", questionIndex=index, choiceIndex=choice, submissionId=submission)
            self.answer_due, self.sent_at = None, now
        elif self.sent_at is not None and now - self.sent_at > timeout_s and self.answer:
            self.rec.counts["answer_timeout"] += self.timed
            self.timed, self.answer_due = False, now  # retry with the same submissionId, untimed
        if self.resync_at is not None and now >= self.resync_at:
            if now - self.last_resync >= RESYNC_EVERY_S:
                self.send("resync", lastSeq=self.last_seq or 0)
                self.resyncing, self.last_resync = True, now
            self.resync_at = None
        self.board.expire(now)

    def drop_answer(self) -> None:
        """Forget the open answer; a timed one still waiting for its reply is a missing sample."""
        self.rec.counts["answer_missing"] += self.timed and self.sent_at is not None
        self.answer = self.sent_at = self.answer_due = None
        self.timed = False

    def settled(self, now: float) -> bool:
        stopping = self.finished or now >= self.deadline
        return self.ended or (stopping and self.answer is None and not self.board.pending)
