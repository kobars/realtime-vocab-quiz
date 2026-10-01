# AI-ASSISTED: a bot's reconnect policy, message handling and leaderboard waits.
from typing import Any

import pytest

from player import Backoff, BoardWait, Player, Recorder, backoff_s


def player(deadline: float = 100.0) -> Player:
    rec = Recorder()
    return Player("VOCAB-42", "bot-0-0", rec, BoardWait(rec, 5), {}, deadline, accuracy=1.0)


def sent(p: Player) -> list[tuple[str, Any]]:
    out = [(m["type"], m.get("questionIndex", m.get("lastSeq"))) for m in p.outbox]
    p.outbox.clear()
    return out


def joined(p: Player, now: float) -> None:
    msg = {"type": "joined", "userId": "u1", "finished": False, "cursor": -1, "cursorOpen": False}
    p.handle(msg, now, Backoff(), 0)


def snapshot(
    p: Player, at: int, now: float, score: int | None = None, status: str = "open"
) -> None:
    you = None if score is None else {"rank": 1, "score": score}
    p.handle({"type": "snapshot", "atSeq": at, "status": status, "you": you}, now, Backoff(), 0)


def frame(p: Player, seq: int, now: float, *, rebase: bool = False) -> None:
    p.handle(
        {"type": "leaderboard", "seq": seq, "rebase": rebase, "entries": []}, now, Backoff(), 0
    )


def refused(p: Player, code: str, request: str, now: float) -> None:
    p.handle({"type": "error", "code": code, "requestType": request}, now, Backoff(), 0)


def test_backoff_is_full_jitter_capped_at_ten_seconds() -> None:
    assert backoff_s(0, 0.999) == 0.249
    assert backoff_s(3, 0.5) == 1.0
    assert backoff_s(12, 0.999) == 9.99


def test_reconnects_follow_the_close_codes_and_reset_after_ten_seconds_joined() -> None:
    backoff = Backoff()
    for code in (1000, 1008, 4001):
        assert Backoff().closed(code, 0, 0.5) is None
    assert backoff.closed(1006, 0, 0.5) == 0.125
    assert backoff.closed(1011, 1, 0.5) == 0.25
    assert backoff.closed(1013, 2, 0.5) == 5.5  # 5 s more after an overload close
    backoff.joined_at = 10
    assert backoff.closed(1006, 20, 0.5) == 0.125  # joined for 10 s: attempt reset


def test_a_bot_joins_answers_and_times_both_latencies() -> None:
    p, backoff = player(), Backoff()
    p.handle(
        {"type": "joined", "userId": "u1", "finished": False, "cursor": -1, "cursorOpen": False},
        1.0,
        backoff,
        0,
    )
    assert sent(p) == [("resync", 0), ("next", 0)]
    assert backoff.joined_at == 1.0
    snapshot(p, 4, 1.1)
    p.handle({"type": "question", "questionId": "q1", "questionIndex": 0}, 1.2, backoff, 0)
    p.due(1.2, timeout_s=5)
    assert sent(p) == [("answer", 0)]
    submission = p.answer[1] if p.answer else ""
    result = {
        "type": "answer_result",
        "submissionId": submission,
        "questionIndex": 0,
        "correctChoiceIndex": 2,
        "pointsAwarded": 140,
        "score": 140,
    }
    p.handle(result, 1.25, backoff, 0)
    assert p.rec.answer_ms == [pytest.approx(50)]
    assert p.key == {"q1": 2}
    assert sent(p) == [("next", 1)]
    p.handle(
        {
            "type": "leaderboard",
            "seq": 5,
            "rebase": False,
            "entries": [{"userId": "u1", "score": 140}],
        },
        1.4,
        backoff,
        0,
    )
    assert p.rec.board_ms == [pytest.approx(150)]
    assert p.last_seq == 5
    assert p.choose("q1") == 2  # accuracy 1 with a learned key


def test_a_seq_gap_schedules_one_resync() -> None:
    p = player()
    snapshot(p, 4, 0)
    for seq in (7, 8, 9):  # one gap, however many frames show it
        frame(p, seq, 1)
    assert p.rec.counts["seq_gaps"] == 1
    p.due(2, timeout_s=5)
    assert sent(p) == [("resync", 4)]
    assert p.rec.counts["resyncs"] == 1
    frame(p, 9, 3, rebase=True)
    assert p.last_seq == 4  # still waiting for the snapshot


def test_a_gap_inside_the_resync_limit_waits_for_it() -> None:
    p = player()
    joined(p, 0)
    snapshot(p, 4, 0.05)
    sent(p)
    frame(p, 7, 0.3)
    p.due(0.6, timeout_s=5)
    assert sent(p) == []
    p.due(1.0, timeout_s=5)
    assert sent(p) == [("resync", 4)]


def test_broadcasts_during_a_resync_are_applied_after_the_snapshot() -> None:
    p = player()
    joined(p, 0)
    for seq in (6, 4):  # 4 is older than the snapshot: dropped, not taken for a restart
        frame(p, seq, 0.1)
    snapshot(p, 5, 0.2)
    frame(p, 7, 0.3)
    assert (p.last_seq, p.rec.counts["seq_gaps"]) == (7, 0)


def test_a_rejoin_keeps_the_resync_limit_and_a_refused_resync_is_retried() -> None:
    p = player()
    joined(p, 0)
    snapshot(p, 4, 0.005)
    sent(p)
    joined(p, 0.01)  # a rejoin, for example after INVALID_STATE
    assert sent(p) == [("next", 0)]
    p.due(0.5, timeout_s=5)
    assert sent(p) == []
    p.due(1.0, timeout_s=5)
    assert sent(p) == [("resync", 4)]
    refused(p, "RATE_LIMITED", "resync", 1.25)
    assert not p.resyncing
    frame(p, 7, 1.5)  # a gap while the retry waits: no second count
    p.due(2.25, timeout_s=5)
    assert sent(p) == [("resync", 4)]
    assert (p.rec.counts["resyncs"], p.rec.counts["seq_gaps"]) == (3, 0)


def test_a_refused_join_or_next_is_sent_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.5)
    p = player()
    joined(p, 0)
    sent(p)
    refused(p, "UNAVAILABLE", "next", 1.0)  # after the backoff: 125 ms, then 250 ms
    p.due(1.0625, timeout_s=5)
    assert sent(p) == []
    p.due(1.125, timeout_s=5)
    assert sent(p) == [("next", 0)]
    refused(p, "UNAVAILABLE", "next", 2.0)
    p.due(2.25, timeout_s=5)
    assert sent(p) == [("next", 0)]
    refused(p, "INVALID_STATE", "next", 3.0)
    refused(p, "RATE_LIMITED", "join", 3.0)  # after 1 s
    assert sent(p) == [("join", None)]
    p.due(3.5, timeout_s=5)
    assert sent(p) == []
    p.due(4.0, timeout_s=5)
    assert sent(p) == [("join", None)]
    refused(p, "RATE_LIMITED", "next", 5.0)
    joined(p, 5.5)  # the join reads the cursor again and drops the pending retry
    assert sent(p) == [("resync", 0), ("next", 0)]
    p.due(6.5, timeout_s=5)
    assert sent(p) == []


def test_a_snapshot_settles_waits_and_can_end_the_quiz() -> None:
    p = player()
    p.board.accepted(140, 0)
    snapshot(p, 3, 0.5, score=140)
    assert p.rec.board_ms == [pytest.approx(500)]
    assert p.board.pending == []
    snapshot(p, 4, 1, status="ended")
    assert p.ended


def test_a_pong_ahead_of_the_last_seq_resyncs_a_second_later() -> None:
    p, backoff = player(), Backoff()
    snapshot(p, 4, 0)
    p.handle({"type": "pong", "seq": None}, 0.5, backoff, 0)
    p.handle({"type": "pong", "seq": 6}, 1, backoff, 0)
    frame(p, 5, 1.5)  # frame 6 never comes
    p.due(1.9, timeout_s=5)
    assert sent(p) == []
    p.due(2, timeout_s=5)
    assert sent(p) == [("resync", 5)]
    snapshot(p, 6, 2.1)
    p.handle({"type": "pong", "seq": 6}, 3, backoff, 0)
    p.due(4.5, timeout_s=5)
    assert (sent(p), p.rec.counts["seq_gaps"]) == ([], 1)


def test_a_retried_answer_keeps_its_submission_id_and_is_never_timed() -> None:
    p, backoff = player(), Backoff()
    p.handle({"type": "question", "questionId": "q1", "questionIndex": 3}, 0, backoff, 0)
    p.due(0, timeout_s=1)
    first = sent(p)
    p.due(2, timeout_s=1)  # no reply within the timeout: count it, retry
    p.due(2, timeout_s=1)
    assert sent(p) == first == [("answer", 3)]
    assert p.rec.counts["answer_timeout"] == 1
    submission = p.answer[1] if p.answer else ""
    p.handle(
        {
            "type": "answer_result",
            "submissionId": submission,
            "questionIndex": 3,
            "correctChoiceIndex": 0,
            "pointsAwarded": 0,
            "score": 0,
        },
        3,
        backoff,
        0,
    )
    assert p.rec.answer_ms == []
    assert p.board.pending == []  # no points, so no leaderboard wait


def test_a_rejoin_error_drops_the_open_answer_and_reads_the_cursor_again() -> None:
    p, backoff = player(), Backoff()
    p.handle({"type": "question", "questionId": "q1", "questionIndex": 0}, 0, backoff, 0)
    p.due(0, timeout_s=5)
    sent(p)
    refused(p, "INVALID_STATE", "answer", 1)
    assert sent(p) == [("join", None)]
    assert (p.answer, p.rec.counts["answer_missing"]) == (None, 1)
    p.finished = True
    assert p.settled(1)
    p.key["q2"], p.accuracy = 1, 0.0
    assert all(p.choose("q2") != 1 for _ in range(20))


def test_a_frame_settles_every_wait_for_its_total_or_lower() -> None:
    rec = Recorder()
    board = BoardWait(rec, timeout_s=5)
    board.accepted(100, now=1.0)
    board.accepted(250, now=2.0)
    board.shown(120, now=1.2)  # shows the first total, not yet the second
    assert rec.board_ms == [pytest.approx(200)]
    assert board.pending == [(250, 2.0)]
    board.shown(250, now=2.05)
    assert rec.board_ms[1] == pytest.approx(50)
    assert board.pending == []


def test_waits_time_out_or_go_missing() -> None:
    rec = Recorder()
    board = BoardWait(rec, timeout_s=1)
    board.accepted(100, now=0.0)
    board.accepted(200, now=0.5)
    board.expire(now=1.2)
    assert rec.counts["board_timeout"] == 1
    board.abandon()
    assert rec.counts["board_missing"] == 1
    assert board.pending == []


def test_merge_adds_samples_and_counts() -> None:
    one, two = Recorder(answer_ms=[1.0]), Recorder(answer_ms=[2.0], board_ms=[3.0])
    one.counts["answers"], two.counts["answers"] = 1, 1
    one.merge(two)
    assert (one.answer_ms, one.board_ms, one.counts["answers"]) == ([1.0, 2.0], [3.0], 2)
