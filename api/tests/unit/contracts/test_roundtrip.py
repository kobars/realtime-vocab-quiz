# AI-ASSISTED: property test: any valid client message survives encode -> parse unchanged.
from hypothesis import given
from hypothesis import strategies as st

from quiz.contracts import ClientMessage, encode, parse_client_message
from quiz.contracts.messages import Answer, GetLeaderboard, Join, Next, Ping, Resync

index = st.integers(min_value=0, max_value=2**53)
client_messages: st.SearchStrategy[ClientMessage] = st.one_of(
    st.builds(
        Join,
        quizId=st.from_regex(r"\A[A-Z0-9-]{3,16}\Z"),
        displayName=st.text(max_size=128),
    ),
    st.builds(Next, questionIndex=index),
    st.builds(
        Answer,
        questionIndex=index,
        choiceIndex=st.integers(min_value=0, max_value=3),
        submissionId=st.uuids().map(str),
    ),
    st.just(Ping()),
    st.builds(Resync, lastSeq=index),
    st.builds(GetLeaderboard, offset=index, limit=st.integers(min_value=1, max_value=200)),
)


@given(client_messages)
def test_encode_then_parse_returns_the_same_message(message: ClientMessage) -> None:
    assert parse_client_message(encode(message)) == message
