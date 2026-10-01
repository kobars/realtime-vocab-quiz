# AI-ASSISTED: the in-process mock identity and ticket store with an injected clock.
"""MOCK: sessions and tickets in one process. A real system would use its identity provider's
sessions and a shared ticket store; the Redis variant is the shared store of this build."""

from dataclasses import dataclass

from quiz.adapters.mock_auth import tokens
from quiz.ports.clock import Clock
from quiz.ports.tickets import Identity


@dataclass(frozen=True, slots=True)
class _Entry:
    digest: str
    identity: Identity
    expires_ms: int


class MemoryTicketStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._sessions: dict[str, _Entry] = {}
        self._tickets: dict[str, _Entry] = {}

    async def create_session(self, display_name: str) -> tuple[Identity, str]:
        identity = Identity(tokens.new_user_id(), tokens.display_name(display_name))
        token = tokens.new_token()
        key = tokens.digest(token)
        self._sessions[key] = _Entry(key, identity, self._clock() + tokens.SESSION_TTL_S * 1000)
        return identity, token

    async def issue_ticket(self, session_token: str) -> str | None:
        now = self._clock()
        session = self._live(self._sessions, session_token, now, consume=False)
        if session is None:
            return None
        self._tickets = {k: e for k, e in self._tickets.items() if now < e.expires_ms}
        ticket = tokens.new_token()
        key = tokens.digest(ticket)
        self._tickets[key] = _Entry(key, session.identity, now + tokens.TICKET_TTL_S * 1000)
        return ticket

    async def redeem(self, ticket: str) -> Identity | None:
        entry = self._live(self._tickets, ticket, self._clock(), consume=True)
        return None if entry is None else entry.identity

    @staticmethod
    def _live(entries: dict[str, _Entry], token: str, now: int, *, consume: bool) -> _Entry | None:
        key = tokens.digest(token)
        entry = entries.pop(key, None) if consume else entries.get(key)
        if entry is None or not tokens.same_digest(entry.digest, token):
            return None
        if now >= entry.expires_ms:
            entries.pop(key, None)
            return None
        return entry
