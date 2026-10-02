# AI-ASSISTED: the gateway's limits: token buckets and abuse rule, connection caps, client address.
"""Bookkeeping only, no I/O; time is integer milliseconds from an injected clock."""

from collections import Counter, OrderedDict
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from ipaddress import IPv4Network, IPv6Network, ip_address

from starlette.requests import HTTPConnection

from quiz.ports.clock import Clock

ABUSE_MS = 10_000  # dropping messages this long without a quiet second: close 1008
QUIET_MS = 1_000  # a gap with no drop that ends an abuse streak; also the RATE_LIMITED interval
ADDRESS_REFILL_S = 60  # a client address's bucket of identity requests or upgrades refills in it


class Verdict(Enum):
    ACCEPT = auto()
    DROP = auto()  # drop the message silently
    NOTIFY = auto()  # drop it and send RATE_LIMITED
    CLOSE = auto()  # send RATE_LIMITED, then close 1008


@dataclass(slots=True)
class TokenBucket:
    rate_per_s: float
    burst: int
    last_ms: int
    tokens: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)

    def take(self, now_ms: int) -> bool:
        """Refill for the time since the last call, then spend one token if there is one."""
        refill = (now_ms - self.last_ms) * self.rate_per_s / 1000
        self.tokens = min(float(self.burst), self.tokens + refill)
        self.last_ms = now_ms
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True

    def full_at(self, now_ms: int) -> bool:
        """Whether the bucket has refilled to the burst by ``now_ms``, like a new one."""
        return (now_ms - self.last_ms) * self.rate_per_s >= (self.burst - self.tokens) * 1000


@dataclass(slots=True)
class RateLimiter:
    rate_per_s: int
    burst: int
    clock: Clock
    bucket: TokenBucket = field(init=False)
    streak_start_ms: int = 0
    last_drop_ms: int | None = None
    last_notice_ms: int | None = None

    def __post_init__(self) -> None:
        self.bucket = TokenBucket(self.rate_per_s, self.burst, self.clock())

    def check(self) -> Verdict:
        now_ms = self.clock()
        if self.bucket.take(now_ms):
            return Verdict.ACCEPT
        if self.last_drop_ms is None or now_ms - self.last_drop_ms > QUIET_MS:
            self.streak_start_ms = now_ms
        self.last_drop_ms = now_ms
        if now_ms - self.streak_start_ms >= ABUSE_MS:
            return Verdict.CLOSE
        if self.last_notice_ms is not None and now_ms - self.last_notice_ms < QUIET_MS:
            return Verdict.DROP
        self.last_notice_ms = now_ms
        return Verdict.NOTIFY


@dataclass(slots=True)
class ConnectionCaps:
    max_total: int
    max_per_ip: int
    total: int = 0
    per_ip: Counter[str] = field(default_factory=Counter)

    def acquire(self, ip: str) -> int | None:
        """Count one socket, or return the HTTP status that refuses it (503 or 429)."""
        if self.total >= self.max_total:
            return 503
        if self.per_ip[ip] >= self.max_per_ip:
            return 429
        self.total += 1
        self.per_ip[ip] += 1
        return None

    def release(self, ip: str) -> None:
        self.total -= 1
        self.per_ip[ip] -= 1
        if self.per_ip[ip] <= 0:
            del self.per_ip[ip]


@dataclass(slots=True)
class AddressRateLimiter:
    """A token bucket per client address. A bucket that has refilled is the same as a new one,
    so it is dropped: only the addresses seen within one refill time take memory."""

    rate_per_s: float
    burst: int
    clock: Clock
    buckets: OrderedDict[str, TokenBucket] = field(default_factory=OrderedDict)

    def allow(self, address: str) -> bool:
        now_ms = self.clock()
        while self.buckets:  # least recently used first
            oldest = next(iter(self.buckets.values()))
            if not oldest.full_at(now_ms):
                break
            self.buckets.popitem(last=False)
        bucket = self.buckets.pop(address, None) or TokenBucket(self.rate_per_s, self.burst, now_ms)
        self.buckets[address] = bucket
        return bucket.take(now_ms)


def _trusted(address: str, proxies: Sequence[IPv4Network | IPv6Network]) -> bool:
    with suppress(ValueError):
        return any(ip_address(address) in network for network in proxies)
    return False


def client_ip(
    peer: str | None, forwarded: Sequence[str], proxies: Sequence[IPv4Network | IPv6Network]
) -> str:
    """The client's address. ``X-Forwarded-For`` is read right to left, and only while each
    hop so far is a trusted proxy: a client cannot pick its own address with the header."""
    hops = [hop.strip() for value in forwarded for hop in value.split(",") if hop.strip()]
    address = peer or "unknown"
    while hops and _trusted(address, proxies):
        address = hops.pop()
    return address


def connection_ip(conn: HTTPConnection, proxies: Sequence[IPv4Network | IPv6Network]) -> str:
    """The client's address of a request or a socket (see ``client_ip``)."""
    peer = conn.client.host if conn.client else None
    return client_ip(peer, conn.headers.getlist("x-forwarded-for"), proxies)
