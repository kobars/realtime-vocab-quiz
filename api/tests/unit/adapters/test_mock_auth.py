# AI-ASSISTED: the mock identity and ticket stores, memory and Redis variants, on one test clock.
from collections.abc import Callable

import pytest
from redis import exceptions as redis_errors

from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.domain.errors import DomainError, ErrorCode
from quiz.ports.tickets import Identity, TicketStore

SESSION_MS, TICKET_MS = 7_200_000, 30_000  # two hours: twice the longest quiz window


class FakeRedis:
    """The commands the Redis variant uses, with EX expiry on the test clock."""

    def __init__(self, now: list[int]) -> None:
        self.now = now
        self.data: dict[str, tuple[str, int]] = {}
        self.calls: list[tuple[str, str, int | None]] = []

    def _live(self, name: str) -> str | None:
        entry = self.data.get(name)
        if entry is None or self.now[0] >= entry[1]:
            self.data.pop(name, None)
            return None
        return entry[0]

    async def set(self, name: str, value: str, *, ex: int) -> bool:
        self.calls.append(("SET", name, ex))
        self.data[name] = (value, self.now[0] + ex * 1000)
        return True

    async def getex(self, name: str, *, ex: int) -> str | None:
        self.calls.append(("GETEX", name, ex))
        if (value := self._live(name)) is not None:
            self.data[name] = (value, self.now[0] + ex * 1000)
        return value

    async def getdel(self, name: str) -> bytes | None:
        self.calls.append(("GETDEL", name, None))
        value = self._live(name)
        self.data.pop(name, None)
        return None if value is None else value.encode()


Make = Callable[[list[int]], TicketStore]
VARIANTS: dict[str, Make] = {
    "memory": lambda now: MemoryTicketStore(lambda: now[0]),
    "redis": lambda now: RedisTicketStore(FakeRedis(now)),
}


@pytest.fixture(params=sorted(VARIANTS))
def store_and_clock(request: pytest.FixtureRequest) -> tuple[TicketStore, list[int]]:
    now = [1_000_000]
    return VARIANTS[request.param](now), now


async def ticket_for(store: TicketStore, name: str = "Ada") -> tuple[Identity, str]:
    identity, token = await store.create_session(name)
    ticket = await store.issue_ticket(token)
    assert ticket is not None
    return identity, ticket


async def test_ticket_redeems_once(store_and_clock: tuple[TicketStore, list[int]]) -> None:
    store, _ = store_and_clock
    identity, ticket = await ticket_for(store)
    assert await store.redeem(ticket) == identity
    assert await store.redeem(ticket) is None


async def test_ticket_expires_after_30_s(store_and_clock: tuple[TicketStore, list[int]]) -> None:
    store, now = store_and_clock
    identity, ticket = await ticket_for(store)
    _, late = await ticket_for(store)
    now[0] += TICKET_MS - 1
    assert await store.redeem(ticket) == identity
    now[0] += 1
    assert await store.redeem(late) is None


async def test_unknown_ticket_fails(store_and_clock: tuple[TicketStore, list[int]]) -> None:
    store, _ = store_and_clock
    await ticket_for(store)
    assert await store.redeem("not-a-ticket") is None
    assert await store.redeem("") is None


async def test_tickets_of_one_session_share_the_user(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, _ = store_and_clock
    identity, token = await store.create_session("  Ada  ")
    first, second = await store.issue_ticket(token), await store.issue_ticket(token)
    assert first is not None
    assert second is not None
    assert first != second
    redeemed = [await store.redeem(first), await store.redeem(second)]
    assert redeemed == [identity, identity]
    assert identity.display_name == "Ada"


async def test_sessions_get_distinct_users_and_tokens(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, _ = store_and_clock
    (a, token_a), (b, token_b) = await store.create_session("A"), await store.create_session("A")
    assert a.user_id != b.user_id
    assert token_a != token_b


async def test_unknown_or_expired_session_gets_no_ticket(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, now = store_and_clock
    _, token = await store.create_session("Ada")
    assert await store.issue_ticket("unknown-token") is None
    now[0] += SESSION_MS
    assert await store.issue_ticket(token) is None


async def test_each_ticket_renews_the_session_for_its_full_lifetime(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, now = store_and_clock
    identity, token = await store.create_session("Ada")
    now[0] += SESSION_MS - 60_000  # 1 h 59 min: the player reconnects in a later quiz
    assert await store.issue_ticket(token) is not None
    now[0] += SESSION_MS - 1
    ticket = await store.issue_ticket(token)
    assert ticket is not None
    assert await store.redeem(ticket) == identity
    now[0] += SESSION_MS
    assert await store.issue_ticket(token) is None


async def test_tokens_and_ids_have_the_wire_format(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, _ = store_and_clock
    identity, token = await store.create_session("Ada")
    ticket = await store.issue_ticket(token)
    assert ticket is not None
    assert len(token) == len(ticket) == 43  # 32 random bytes in base64url without padding
    assert set(token + ticket + identity.user_id) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert 1 <= len(identity.user_id) <= 64


@pytest.mark.parametrize("name", ["", "   ", "x" * 33, " " * 100 + "x" * 29])
async def test_bad_display_name_is_refused(
    store_and_clock: tuple[TicketStore, list[int]], name: str
) -> None:
    store, _ = store_and_clock
    with pytest.raises(DomainError) as refused:
        await store.create_session(name)
    assert refused.value.code is ErrorCode.INVALID_MESSAGE


async def test_display_name_is_nfc_normalized(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, _ = store_and_clock
    identity, _ = await store.create_session("Cafe\u0301")  # e + combining acute accent
    assert identity.display_name == "Caf\u00e9"


async def test_redis_variant_uses_set_ex_getex_and_getdel() -> None:
    redis = FakeRedis([0])
    store = RedisTicketStore(redis)
    _, token = await store.create_session("Ada")
    ticket = await store.issue_ticket(token)
    assert ticket is not None
    await store.redeem(ticket)
    commands = [(cmd, ex) for cmd, _, ex in redis.calls]
    assert commands == [("SET", 7_200), ("GETEX", 7_200), ("SET", 30), ("GETDEL", None)]
    names = [name for _, name, _ in redis.calls]
    assert not [name for name in names if token in name or ticket in name]  # digests only


async def test_memory_variant_drops_expired_sessions_and_tickets() -> None:
    now = [0]
    store = MemoryTicketStore(lambda: now[0])
    for _ in range(1_000):
        _, token = await store.create_session("Ada")
        assert await store.issue_ticket(token) is not None
    now[0] += SESSION_MS
    _, token = await store.create_session("Ada")
    assert await store.issue_ticket(token) is not None
    assert len(store._sessions) == len(store._tickets) == 1  # noqa: SLF001


class DownRedis:
    """Every command fails the way redis-py fails when the server is unreachable."""

    def __init__(self, error: redis_errors.RedisError) -> None:
        self.error = error

    async def _fail(self, *_: object, **__: object) -> None:
        raise self.error

    set = getex = getdel = _fail


REFUSALS = [  # Redis refusing writes: a read-only replica, maxmemory, a failed AOF write
    redis_errors.ReadOnlyError("You can't write against a read only replica."),
    redis_errors.OutOfMemoryError("command not allowed when used memory > 'maxmemory'."),
    redis_errors.ResponseError("MISCONF Errors writing to the AOF file: No space left on device"),
]


@pytest.mark.parametrize(
    ("raised", "seen"),
    [
        (redis_errors.ConnectionError("down"), ConnectionError),
        (redis_errors.TimeoutError("slow"), TimeoutError),
        *((refusal, ConnectionError) for refusal in REFUSALS),
        (
            redis_errors.ResponseError("WRONGTYPE Operation against a key"),
            redis_errors.ResponseError,
        ),
    ],
    ids=["unreachable", "slow", "READONLY", "OOM", "MISCONF", "another reply error"],
)
async def test_redis_variant_raises_the_builtin_errors_when_redis_is_unreachable_or_refuses(
    raised: redis_errors.RedisError, seen: type[Exception]
) -> None:
    store = RedisTicketStore(DownRedis(raised))
    for call in (store.create_session("Ada"), store.issue_ticket("t"), store.redeem("t")):
        with pytest.raises(seen):
            await call
