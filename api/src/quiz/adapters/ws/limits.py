# AI-ASSISTED: the gateway's limits: token bucket and abuse rule, connection caps, client address.
"""Bookkeeping only, no I/O; time is integer milliseconds from an injected clock."""

from collections import Counter
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from ipaddress import IPv4Network, IPv6Network, ip_address

from quiz.ports.clock import Clock

ABUSE_MS = 10_000  # dropping messages this long without a quiet second: close 1008
QUIET_MS = 1_000  # a gap with no drop that ends an abuse streak; also the RATE_LIMITED interval


class Verdict(Enum):
    ACCEPT = auto()
    DROP = auto()  # drop the message silently
    NOTIFY = auto()  # drop it and send RATE_LIMITED
    CLOSE = auto()  # send RATE_LIMITED, then close 1008


@dataclass(slots=True)
class RateLimiter:
    rate_per_s: int
    burst: int
    clock: Clock
    tokens: float = field(init=False)
    last_ms: int = field(init=False)
    streak_start_ms: int = 0
    last_drop_ms: int | None = None
    last_notice_ms: int | None = None

    def __post_init__(self) -> None:
        self.tokens, self.last_ms = float(self.burst), self.clock()

    def check(self) -> Verdict:
        now_ms = self.clock()
        refill = (now_ms - self.last_ms) * self.rate_per_s / 1000
        self.tokens = min(float(self.burst), self.tokens + refill)
        self.last_ms = now_ms
        if self.tokens >= 1:
            self.tokens -= 1
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
