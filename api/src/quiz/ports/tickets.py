# AI-ASSISTED: the identity and ticket port; the mock auth implements it.
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    display_name: str


class TicketStore(Protocol):
    async def create_session(self, display_name: str) -> tuple[Identity, str]:
        """Return the new user and its session token."""
        ...

    async def issue_ticket(self, session_token: str) -> str | None:
        """Return a single-use ticket for the session's user; None for an unknown session."""
        ...

    async def redeem(self, ticket: str) -> Identity | None:
        """Consume the ticket once; None when it is unknown, used or expired."""
        ...
