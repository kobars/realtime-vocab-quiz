# AI-ASSISTED: the mock identity and ticket store in Redis, shared by every API node.
"""MOCK: sessions and tickets in Redis. A real system would use its identity provider's sessions;
the ticket mechanism (SET EX 30, then GETDEL) is what a real build would keep.

An unreachable Redis, or one that refuses writes, leaves as the built-in ``ConnectionError`` or
``TimeoutError`` (``quiz.adapters.redis_outage``), so the gateway answers it with 503."""

import json
from collections.abc import Awaitable
from typing import Protocol

from quiz.adapters.mock_auth import tokens
from quiz.adapters.redis_outage import reachable
from quiz.ports.tickets import Identity

SESSION_KEY, TICKET_KEY = "auth:session:", "auth:ticket:"


class RedisCommands(Protocol):
    """The subset of ``redis.asyncio.Redis`` this store uses."""

    def set(self, name: str, value: str, *, ex: int) -> Awaitable[object]: ...

    def get(self, name: str) -> Awaitable[bytes | str | None]: ...

    def getdel(self, name: str) -> Awaitable[bytes | str | None]: ...


class RedisTicketStore:
    """Keys hold a token's digest, never the token; Redis EX does the expiry."""

    def __init__(self, redis: RedisCommands) -> None:
        self._redis = redis

    async def create_session(self, display_name: str) -> tuple[Identity, str]:
        identity = Identity(tokens.new_user_id(), tokens.display_name(display_name))
        token = tokens.new_token()
        await self._put(SESSION_KEY, token, identity, tokens.SESSION_TTL_S)
        return identity, token

    async def issue_ticket(self, session_token: str) -> str | None:
        with reachable():
            raw = await self._redis.get(SESSION_KEY + tokens.digest(session_token))
        identity = _identity(raw, session_token)
        if identity is None:
            return None
        ticket = tokens.new_token()
        await self._put(TICKET_KEY, ticket, identity, tokens.TICKET_TTL_S)
        return ticket

    async def redeem(self, ticket: str) -> Identity | None:
        with reachable():
            raw = await self._redis.getdel(TICKET_KEY + tokens.digest(ticket))
        return _identity(raw, ticket)

    async def _put(self, prefix: str, token: str, identity: Identity, ttl_s: int) -> None:
        key = tokens.digest(token)
        value = json.dumps({"digest": key, "uid": identity.user_id, "name": identity.display_name})
        with reachable():
            await self._redis.set(prefix + key, value, ex=ttl_s)


def _identity(raw: bytes | str | None, token: str) -> Identity | None:
    if raw is None:
        return None
    entry = json.loads(raw)
    if not tokens.same_digest(entry["digest"], token):
        return None
    return Identity(entry["uid"], entry["name"])
