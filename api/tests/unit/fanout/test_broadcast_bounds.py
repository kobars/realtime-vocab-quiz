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


def relay_reading(sockets: Mock, ranks: Ranks) -> Relay:
    """A relay whose shifted read returns ``ranks``."""
    store = Mock(spec=Store)
    store.ranks_of.return_value = ranks
    return Relay("Q", store, sockets, LIMITS)


@pytest.mark.parametrize(
    ("player_count", "rank", "updates"),
    [(3, 3, 0), (4, 3, 1), (4, 2, 0)],
    ids=["full-list-max-players", "one-more-player", "rank-top-n"],
)
async def test_a_shifted_rank_goes_out_only_above_full_list_max_and_below_the_top_n(
    sockets: Mock, player_count: int, rank: int, updates: int
) -> None:
    relay = relay_reading(sockets, Ranks(1, "open", player_count, {"u": Row(rank, "u", "U", 0)}))
    await relay.relay(leaderboard(1, player_count))
    await relay.shifted()
    assert sockets.send_to.call_count == updates


@pytest.mark.parametrize(("read_seq", "updates"), [(1, 1), (2, 2)], ids=["same-seq", "newer-seq"])
async def test_a_shifted_read_at_the_seq_of_the_frame_keeps_the_frames_rank(
    sockets: Mock, read_seq: int, updates: int
) -> None:
    relay = relay_reading(sockets, Ranks(read_seq, "open", 4, {"u": Row(4, "u", "U", 100)}))
    await relay.relay(leaderboard(1, 4, ("u", 3, 100)))  # the frame sends u its rank 3
    await relay.shifted()
    assert sockets.send_to.call_count == updates
