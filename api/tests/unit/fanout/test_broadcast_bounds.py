# AI-ASSISTED: the exact boundaries of the shifted rank_update: full_list_max, top_n, the seq guard.
import json
from unittest.mock import Mock

import pytest

from quiz.fanout.broadcast import Relay
from quiz.ports.store import Limits, Ranks, Row, Store

LIMITS = Limits(top_n=2, full_list_max=3)


def leaderboard(seq: int, player_count: int, *ranks: tuple[str, int, int]) -> str:
    frame = {"v": 1, "type": "leaderboard", "seq": seq, "rebase": False}
    frame |= {"playerCount": player_count, "onlineCount": 1, "entries": []}
    return json.dumps({"frame": frame, "ranks": ranks}, separators=(",", ":"))


def store_reading(ranks: Ranks) -> Mock:
    """A store whose rank read returns ``ranks``."""
    store = Mock(spec=Store)
    store.ranks_of.return_value = ranks
    return store


@pytest.mark.parametrize(
    ("player_count", "rank", "updates"),
    [(3, 3, 0), (4, 3, 1), (4, 2, 0)],
    ids=["full-list-max-players", "one-more-player", "rank-top-n"],
)
async def test_a_shifted_rank_goes_out_only_above_full_list_max_and_below_the_top_n(
    sockets: Mock, player_count: int, rank: int, updates: int
) -> None:
    store = store_reading(Ranks(1, "open", player_count, {"u": Row(rank, "u", "U", 0)}))
    relay = Relay("Q", store, sockets, LIMITS)
    await relay.relay(leaderboard(1, player_count))
    await relay.shifted()
    assert sockets.send_to.call_count == updates


@pytest.mark.parametrize(("read_seq", "updates"), [(1, 1), (2, 2)], ids=["same-seq", "newer-seq"])
async def test_a_shifted_read_at_the_seq_of_the_frame_keeps_the_frames_rank(
    sockets: Mock, read_seq: int, updates: int
) -> None:
    store = store_reading(Ranks(read_seq, "open", 4, {"u": Row(4, "u", "U", 100)}))
    relay = Relay("Q", store, sockets, LIMITS)
    await relay.relay(leaderboard(1, 4, ("u", 3, 100)))  # the frame sends u its rank 3
    await relay.shifted()
    assert sockets.send_to.call_count == updates


async def test_a_second_shifted_read_waits_for_a_newer_frame(sockets: Mock) -> None:
    store = store_reading(Ranks(1, "open", 4, {"u": Row(4, "u", "U", 100)}))
    relay = Relay("Q", store, sockets, LIMITS)
    await relay.relay(leaderboard(1, 4))
    await relay.shifted()
    await relay.shifted()  # no frame since the read at seq 1
    assert store.ranks_of.call_count == 1


async def test_a_repair_at_an_older_seq_tracks_ranks_from_the_snapshots(sockets: Mock) -> None:
    store = store_reading(Ranks(100, "open", 4, {"u": Row(4, "u", "U", 100)}))
    relay = Relay("Q", store, sockets, LIMITS)
    await relay.relay(leaderboard(100, 4))
    await relay.shifted()  # rank 4 at seq 100
    relay.repaired(Ranks(95, "open", 4, {"u": Row(3, "u", "U", 90)}))  # the store lost seq 96-100
    store.ranks_of.return_value = Ranks(96, "open", 4, {"u": Row(3, "u", "U", 90)})
    await relay.relay(leaderboard(95, 4))  # the snapshot holds it
    await relay.relay(leaderboard(96, 4))
    await relay.shifted()  # the rank the snapshot gave: no second one
    store.ranks_of.return_value = Ranks(97, "open", 4, {"u": Row(5, "u", "U", 90)})
    await relay.relay(leaderboard(97, 4))
    await relay.shifted()
    assert (sockets.broadcast.call_count, store.ranks_of.call_count) == (3, 3)
    assert sockets.send_to.call_count == 2  # rank 4 at seq 100, rank 5 at seq 97
