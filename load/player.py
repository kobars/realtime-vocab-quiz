# AI-ASSISTED: one bot's protocol rules: reconnect backoff, play state and latency samples.
"""What a bot does with each server message and when it sends the next one; no I/O.

Times are monotonic seconds; reported latencies are milliseconds. The bot follows the web
client: full-jitter backoff (none after close 1000, 1008 or 4001; 5 s more after 1013), one
``resync`` after each ``joined``, after a ``seq`` gap and after a ``pong`` ahead of its ``seq``
(at most one per second; every frame from a gap, or while a resync is due or in flight, waits
for the ``snapshot``, and only an applied frame settles a leaderboard wait), a refused request
sent again after 1 s (``RATE_LIMITED``) or the backoff (``UNAVAILABLE``), and an open answer
resent with the same ``submissionId``, also after a reconnect. A sample slower than the timeout
counts as timed out, wherever it is taken.
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
RETRY_ERRORS = frozenset({"RATE_LIMITED", "UNAVAILABLE"})
RETRIED = frozenset({"join", "next"})  # sent again as they were after a refusal


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
    ``board_ms``: ``answer_result`` with points → the first frame that shows the new total.
    Reply and broadcast have no order: ``board_first`` counts the totals a frame showed before
    their ``answer_result``, which have no ``board_ms`` sample."""

    answer_ms: list[float] = field(default_factory=list)
    board_ms: list[float] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    def merge(self, other: Recorder) -> None:
        self.answer_ms += other.answer_ms
        self.board_ms += other.board_ms
        self.counts += other.counts

    def timed_out(self, name: str, elapsed_s: float, timeout_s: float) -> bool:
        """Count ``<name>_timeout`` when the sample took longer than ``timeout_s``."""
        late = elapsed_s > timeout_s
        self.counts[f"{name}_timeout"] += late
        return late


@dataclass(slots=True)
class BoardWait:
    """The totals one player waits to see on a ``leaderboard`` or ``rank_update``."""

    recorder: Recorder
    timeout_s: float
    pending: list[tuple[int, float]] = field(default_factory=list)  # (total, accepted at)
    best: int = 0  # the highest own total a frame has shown

    def accepted(self, total: int, now: float) -> None:
        if total <= self.best:
            self.recorder.counts["board_first"] += 1
        else:
            self.pending.append((total, now))

    def shown(self, total: int, now: float) -> None:
        """A frame shows ``total``: it settles every wait for that total or a lower one."""
        self.best = max(self.best, total)
        keep = []
        for want, since in self.pending:
            if want > total:
                keep.append((want, since))
            elif not self.recorder.timed_out("board", now - since, self.timeout_s):
                self.recorder.board_ms.append((now - since) * 1000)
        self.pending = keep

    def expire(self, now: float) -> None:
        timed_out = self.recorder.timed_out
        self.pending = [
            p for p in self.pending if not timed_out("board", now - p[1], self.timeout_s)
        ]

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
    sent: bool = False  # the open answer went out at least once
    sent_at: float | None = None  # the last send of the open answer on this connection
    timed: bool = False  # the open answer's first send: its reply is a latency sample
    last_seq: int | None = None
    resyncing: bool = False  # a resync is in flight: broadcasts wait in ``buffered``
    resync_at: float | None = None
    last_resync: float = -math.inf
    # the frames held for the snapshot: (seq, rebase, the own total it shows or None)
    buffered: list[tuple[int, bool, int | None]] = field(default_factory=list)
    pong_check: tuple[int, float] | None = None  # (pong seq, when last_seq must have reached it)
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)  # the last of each RETRIED
    retry_at: dict[str, float] = field(default_factory=dict)
    refusals: int = 0  # refusals in a row: the UNAVAILABLE backoff attempt
    finished: bool = False
    ended: bool = False
    outbox: list[dict[str, Any]] = field(default_factory=list)

    def send(self, kind: str, **body: Any) -> None:  # noqa: ANN401
        message = {"v": 1, "type": kind, **body}
        if kind in RETRIED:
            self.requests[kind] = message
        self.outbox.append(message)

    def choose(self, question_id: str) -> int:
        correct = self.key.get(question_id)
        if correct is None:
            return random.randrange(4)  # noqa: S311 - load pattern, not security
        if random.random() < self.accuracy:  # noqa: S311
            return correct
        return random.choice([c for c in range(4) if c != correct])  # noqa: S311

    def on_seq(self, seq: int, rebase: bool, score: int | None, now: float) -> None:  # noqa: FBT001
        """Apply a leaderboard frame in ``seq`` order, as the web client's ``SeqTracker`` does:
        only an applied frame shows the own ``score``; one before the snapshot, after a gap or
        while a resync is due or in flight waits in ``buffered``."""
        last = self.last_seq
        if last is not None and not self.resyncing and self.resync_at is None:
            if seq == last:
                return
            if seq == last + 1 or (rebase and seq > last):
                self.last_seq = seq
                if score is not None:
                    self.board.shown(score, now)
                return
            # a gap, or the counter went back after a store restart
            self.gap(now + (random.uniform(0, 0.25) if seq > last else 0))  # noqa: S311
        self.buffered.append((seq, rebase, score))

    def gap(self, resync_at: float) -> None:
        """Count a gap and schedule its resync, once while a resync is pending or in flight."""
        if self.resync_at is None and not self.resyncing:
            self.rec.counts["seq_gaps"] += 1
            self.resync_at = resync_at

    def resync(self, now: float) -> None:
        """Send ``resync`` now, or when the server's limit of one per second allows it."""
        if now - self.last_resync < RESYNC_EVERY_S:
            self.resync_at = self.last_resync + RESYNC_EVERY_S
            return
        self.send("resync", lastSeq=self.last_seq or 0)
        self.rec.counts["resyncs"] += 1
        self.resyncing, self.resync_at, self.last_resync = True, None, now

    def handle(self, msg: dict[str, Any], now: float, backoff: Backoff, think_s: float) -> None:  # noqa: C901, PLR0912
        kind = msg["type"]
        if kind != "error":
            self.refusals = 0
        if kind == "joined":
            backoff.joined_at, self.user_id = now, msg["userId"]
            self.resyncing, self.resync_at, self.pong_check = False, None, None
            self.buffered.clear()
            self.retry_at.clear()  # the join supersedes them: it reads the cursor again
            self.resync(now)
            self.finished = msg["finished"]
            open_index = self.answer[0] if self.answer else None
            if open_index == msg["cursor"] and not msg["cursorOpen"]:
                self.answer_due = now  # scored, but its reply was lost: the resend replays it
            elif not self.finished and now < self.deadline:
                self.send("next", questionIndex=msg["cursor"] + (0 if msg["cursorOpen"] else 1))
        elif kind == "question":
            self.question_id, index = msg["questionId"], msg["questionIndex"]
            if self.answer is not None and self.answer[0] == index:
                if self.sent:  # re-served after a send: resend now, untimed
                    self.rec.counts["answer_missing"] += self.timed
                    self.answer_due, self.timed = now, False
            else:
                self.drop_answer()
                self.answer = (index, str(uuid.uuid4()), self.choose(self.question_id))
                self.answer_due = now + think_s * random.uniform(0.5, 1.5)  # noqa: S311
                self.timed = True
        elif kind == "answer_result" and self.answer and msg["submissionId"] == self.answer[1]:
            self.replied(msg, now)
        elif kind == "finished":
            self.finished = True
        elif kind == "leaderboard":
            own = (e["score"] for e in msg["entries"] if e["userId"] == self.user_id)
            self.on_seq(msg["seq"], msg["rebase"], next(own, None), now)
        elif kind == "rank_update":
            self.board.shown(msg["score"], now)
        elif kind == "snapshot":
            self.snapshot(msg, now)
        elif kind == "pong":
            ahead = self.last_seq is not None and (msg["seq"] or 0) > self.last_seq
            if ahead and self.pong_check is None:
                self.pong_check = (msg["seq"], now + RESYNC_EVERY_S)
        elif kind == "quiz_ended":
            self.ended = True
        elif kind == "error":
            self.error(msg["code"], msg["requestType"], now)

    def replied(self, msg: dict[str, Any], now: float) -> None:
        """The open answer's ``answer_result``: only the reply to a timed send is a sample."""
        self.key[self.question_id] = msg["correctChoiceIndex"]
        sent_at, timed = self.sent_at, self.timed
        self.timed = False  # answered: not a missing sample
        self.drop_answer()
        elapsed = now - sent_at if timed and sent_at is not None else None
        if elapsed is not None and not self.rec.timed_out("answer", elapsed, self.board.timeout_s):
            self.rec.answer_ms.append(elapsed * 1000)
            if msg["pointsAwarded"] > 0:  # never for a replay: its total may be shown already
                self.board.accepted(msg["score"], now)
        self.rec.counts["answers"] += 1
        if now < self.deadline:
            self.send("next", questionIndex=msg["questionIndex"] + 1)

    def error(self, code: str, request: str | None, now: float) -> None:
        self.rec.counts[f"error_{code}"] += 1
        if code == "QUIZ_ENDED":
            self.ended = True
        elif code in RETRY_ERRORS:
            self.refused(request, code, now)
        elif code in REJOIN_ERRORS:  # read the stored cursor again
            self.drop_answer()
            self.send("join", quizId=self.quiz_id, displayName=self.name)

    def snapshot(self, msg: dict[str, Any], now: float) -> None:
        self.last_seq, self.resyncing = msg["atSeq"], False
        self.ended |= msg["status"] == "ended"
        if msg["you"] is not None:
            self.board.shown(msg["you"]["score"], now)
        buffered, self.buffered = self.buffered, []
        newer = sorted((frame for frame in buffered if frame[0] > msg["atSeq"]), key=lambda f: f[0])
        for seq, rebase, score in newer:
            self.on_seq(seq, rebase, score, now)

    def refused(self, kind: str | None, code: str, now: float) -> None:
        """The server did not do the request: send it again after 1 s or the backoff."""
        rnd = random.random()  # noqa: S311
        wait = RESYNC_EVERY_S if code == "RATE_LIMITED" else backoff_s(self.refusals, rnd)
        self.refusals += 1
        if kind == "resync":
            self.resyncing, self.resync_at = False, now + wait
        elif kind in RETRIED:
            self.retry_at[kind] = now + wait

    def due(self, now: float) -> None:
        """Send what the clock asks for: the answer after its think time, resyncs, retries."""
        if self.answer_due is not None and now >= self.answer_due and self.answer:
            if not self.sent and now >= self.deadline:  # no new answers after the deadline
                self.drop_answer()
            else:
                index, submission, choice = self.answer
                self.send(
                    "answer", questionIndex=index, choiceIndex=choice, submissionId=submission
                )
                self.answer_due, self.sent_at, self.sent = None, now, True
        elif self.sent_at is not None and now - self.sent_at > self.board.timeout_s and self.answer:
            self.rec.counts["answer_timeout"] += self.timed
            self.timed, self.answer_due = False, now  # retry with the same submissionId, untimed
        for kind, at in list(self.retry_at.items()):
            if now >= at:
                del self.retry_at[kind]
                self.outbox.append(self.requests[kind])
        if self.pong_check is not None and now >= self.pong_check[1]:
            if self.last_seq is not None and self.last_seq < self.pong_check[0]:
                self.gap(now)
            self.pong_check = None
        if self.resync_at is not None and now >= self.resync_at:
            self.resync(now)
        self.board.expire(now)

    def drop_answer(self) -> None:
        """Forget the open answer; a timed one still waiting for its reply is a missing sample."""
        self.rec.counts["answer_missing"] += self.timed and self.sent_at is not None
        self.answer = self.sent_at = self.answer_due = None
        self.timed = self.sent = False

    def disconnected(self) -> None:
        """No wait crosses a connection: it would time the reconnect. An unsent answer is
        dropped (``joined`` serves its question again); a sent one stays open, untimed, for a
        resend with the same ``submissionId``. Board waits are missing samples."""
        if self.sent:
            self.rec.counts["answer_missing"] += self.timed
            self.timed, self.sent_at, self.answer_due = False, None, None
        else:
            self.drop_answer()
        self.board.abandon()
        self.outbox.clear()

    def settled(self, now: float) -> bool:
        stopping = self.finished or now >= self.deadline
        return self.ended or (stopping and self.answer is None and not self.board.pending)
