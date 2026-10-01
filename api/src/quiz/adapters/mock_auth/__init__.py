# AI-ASSISTED: the mock identity and ticket package.
"""MOCK: identity and tickets. A real system would use its identity provider (OIDC) for users."""

from quiz.adapters.mock_auth.memory import MemoryTicketStore as MemoryTicketStore
from quiz.adapters.mock_auth.redis_store import RedisTicketStore as RedisTicketStore
