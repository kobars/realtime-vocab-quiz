# AI-ASSISTED: stateful test of the session state machine: C1, C2, C3, C6, answer/skip exclusivity,
# accepted answers and the deadline.
from collections import Counter

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.events import (
    AnswerScored,
    Event,
    QuestionServed,
    QuestionSkipped,
    QuizEnded,
    StandingsBroadcast,
)
from quiz.domain.scoring import score_answer
from quiz.domain.session import (
    Answer,
    Command,
    End,
    Join,
    Question,
    QuizState,
    ServeNext,
    Step,
    Tick,
    new_quiz,
    transition,
)

T = 20  # short, so every ms changes the points and the late edge is hit often
QUESTIONS = tuple(Question(f"q{i}", i % 4) for i in range(3))
users = st.sampled_from(["ann", "bob", "cy"])
# A small pool of submission ids per player makes retries and reuse common.
submissions = st.sampled_from(["s1", "s2", "s3", "s4"])


def outcome(state: QuizState, command: Command, now: int) -> Step | ErrorCode:
    try:
        return transition(state, command, now)
    except DomainError as err:
        return err.code


class SessionMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.initial = self.state = new_quiz(
            QUESTIONS, start_ms=0, window_ms=100 * T, time_limit_ms=T
        )
        self.now = 0
        self.log: list[tuple[Command, int, Step | ErrorCode]] = []
        self.results: dict[tuple[str, str], AnswerScored] = {}
        self.closed: set[tuple[str, int]] = set()
        self.serves: dict[tuple[str, int], int] = {}
        self.points: Counter[str] = Counter()
        self.unbroadcast: dict[str, int] = {}  # the last answer_result total since the last frame
        self.seqs: list[int] = []
        self.last_frame: dict[str, int] = {}  # user -> total in the last broadcast

    def apply(self, command: Command) -> Step | ErrorCode:
        out = outcome(self.state, command, self.now)
        self.log.append((command, self.now, out))
        if isinstance(out, Step):
            self.state = out.state
            for event in out.events:
                self.record(event)
        return out

    def record(self, event: Event) -> None:
        match event:
            case AnswerScored() | QuestionSkipped():
                key = (event.user_id, event.question_index)
                assert key not in self.closed, "a question closed twice"
                self.closed.add(key)
                if isinstance(event, AnswerScored):
                    self.points[event.user_id] += event.points
                    self.unbroadcast[event.user_id] = event.total
            case QuestionServed():
                self.serves[event.user_id, event.question_index] = event.serve_ms
            case StandingsBroadcast() | QuizEnded():
                self.seqs.append(event.seq)
                totals = {row.standing.user_id: row.standing.total for row in event.entries}
                for user_id, total in self.unbroadcast.items():
                    assert totals[user_id] == total  # C3
                self.unbroadcast.clear()
                self.last_frame = totals
            case _:
                pass

    def cursor(self, user_id: str) -> int:
        player = self.state.players.get(user_id)
        return player.cursor if player else -1

    @initialize(user_ids=st.lists(users, min_size=1, unique=True))
    def join_at_start(self, user_ids: list[str]) -> None:
        for user_id in user_ids:
            self.apply(Join(user_id))

    @rule(dt=st.integers(-5, T + T // 2))  # a negative step is the server clock stepping back
    def advance(self, dt: int) -> None:
        self.now += dt

    # A jump to around the deadline, so the deadline tick and the post-deadline refusals run too.
    @precondition(lambda self: len(self.log) > 10)
    @rule(dt=st.integers(-1, T))
    def pass_deadline(self, dt: int) -> None:
        self.now = max(self.now, self.state.deadline_ms + dt)

    @rule(user_id=users)
    def join(self, user_id: str) -> None:
        open_ = self.state.is_open(self.now)
        out = self.apply(Join(user_id))
        assert open_ or out is ErrorCode.QUIZ_ENDED

    @rule(user_id=users, offset=st.sampled_from([1, 1, 1, 0, 2, -1]))  # mostly a fresh serve
    def next(self, user_id: str, offset: int) -> None:
        index = self.cursor(user_id) + offset
        before = self.state
        out = self.apply(ServeNext(user_id, index))
        if not before.is_open(self.now):  # checked before the player exists
            assert out is ErrorCode.QUIZ_ENDED
        if isinstance(out, Step) and isinstance(out.reply, QuestionServed):
            assert out.reply.serve_ms == (self.serves[user_id, index] if offset == 0 else self.now)
            if offset == 0:  # a duplicate next writes nothing
                assert (out.state, out.events) == (before, ())

    @rule(
        user_id=users,
        offset=st.sampled_from([0, 0, 0, 1, -1]),
        correct=st.booleans(),
        sid=submissions,
    )
    def answer(self, user_id: str, offset: int, correct: bool, sid: str) -> None:  # noqa: FBT001
        index = max(0, self.cursor(user_id)) + offset
        choice = (QUESTIONS[index % 3].correct_choice + (0 if correct else 1)) % 4
        before = self.state
        player = before.players.get(user_id)
        stored = self.results.get((user_id, sid))
        out = self.apply(Answer(user_id, index, choice, sid))
        if stored is not None and stored.question_index == index:  # layer 1: a replay
            assert out == Step(before, (), stored)
        elif stored is not None:  # a submission id reused on another question
            assert out is ErrorCode.INVALID_MESSAGE
        elif not before.is_open(self.now):  # after the deadline a new answer writes nothing
            assert out is ErrorCode.QUIZ_ENDED
        elif player is None:
            assert out is ErrorCode.NOT_JOINED
        elif index == player.cursor and player.cursor_open:  # a fresh answer is accepted
            assert isinstance(out, Step)
            assert isinstance(out.reply, AnswerScored)
            self.results[user_id, sid] = out.reply
            elapsed = max(0, self.now - self.serves[user_id, index])
            assert out.reply.late == (elapsed > T)
            assert out.reply.points == score_answer(
                correct=correct, elapsed_ms=elapsed, time_limit_ms=T
            )
        elif 0 <= index <= player.cursor:
            assert out is ErrorCode.ALREADY_ANSWERED  # layer 2
        else:
            assert out is ErrorCode.QUESTION_NOT_OPEN

    @rule()
    def tick(self) -> None:
        before = self.state
        out = self.apply(Tick())
        if before.ended_ms is None and not before.is_open(self.now):  # the deadline has passed
            assert isinstance(out, Step)
            assert isinstance(out.reply, QuizEnded)
            assert out.reply.at_ms == before.deadline_ms

    @precondition(lambda self: len(self.log) > 40)
    @rule()
    def end(self) -> None:
        self.apply(End())

    @invariant()
    def score_is_the_sum_of_points(self) -> None:  # C1
        for user_id, player in self.state.players.items():
            assert player.standing.total == self.points[user_id]

    @invariant()
    def broadcast_seq_is_contiguous(self) -> None:  # C2
        assert self.seqs == list(range(1, len(self.seqs) + 1))
        assert self.state.seq == len(self.seqs)

    @invariant()
    def passed_questions_are_closed_once(self) -> None:  # an answer and a skip are exclusive
        for user_id, player in self.state.players.items():
            passed = player.cursor + (0 if player.cursor_open else 1)
            assert {i for user, i in self.closed if user == user_id} == set(range(passed))

    @invariant()
    def changed_standings_are_dirty(self) -> None:
        totals = {user_id: p.standing.total for user_id, p in self.state.players.items()}
        assert self.state.dirty or self.state.ended_ms is not None or totals == self.last_frame

    def teardown(self) -> None:
        # C6: every outcome is a function of the commands and the injected clock alone.
        state = self.initial
        for command, now, logged in self.log:
            replayed = outcome(state, command, now)
            assert replayed == logged
            if isinstance(replayed, Step):
                state = replayed.state


TestSessionMachine = SessionMachine.TestCase
