# AI-ASSISTED: the mock identity and ticket stores, memory and Redis variants, on one test clock.
from collections.abc import Callable

import pytest

from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.domain.errors import DomainError, ErrorCode
from quiz.ports.tickets import Identity, TicketStore

SESSION_MS, TICKET_MS = 86_400_000, 30_000


class FakeRedis:
    """The three commands the Redis variant uses, with EX expiry on the test clock."""

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

    async def get(self, name: str) -> str | None:
        self.calls.append(("GET", name, None))
        return self._live(name)

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
    now[0] += SESSION_MS - 1
    assert await store.issue_ticket(token) is not None
    now[0] += 1
    assert await store.issue_ticket(token) is None


async def test_tokens_and_ids_have_the_wire_format(
    store_and_clock: tuple[TicketStore, list[int]],
) -> None:
    store, _ = store_and_clock
    identity, ticket = await ticket_for(store)
    assert len(ticket) == 43  # 32 random bytes in base64url without padding
    assert set(ticket + identity.user_id) <= set(
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


async def test_redis_variant_uses_set_ex_and_getdel() -> None:
    redis = FakeRedis([0])
    store = RedisTicketStore(redis)
    _, ticket = await ticket_for(store)
    await store.redeem(ticket)
    commands = [(cmd, ex) for cmd, _, ex in redis.calls]
    assert commands == [("SET", 86_400), ("GET", None), ("SET", 30), ("GETDEL", None)]
    assert all(ticket not in name for _, name, _ in redis.calls)  # keys hold a digest only
