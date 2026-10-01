# AI-ASSISTED: shared rules of the mock identity: lifetimes, random tokens, digests, display names.
"""MOCK: session and ticket rules. A real system would take the user from its identity provider.

Tokens are stored and looked up only by their SHA-256 digest, so a lookup never compares the
secret itself; the digest found is then checked again with a constant-time comparison.
"""

import hashlib
import hmac
import secrets
import unicodedata

from quiz.domain.errors import DomainError, ErrorCode

SESSION_TTL_S = 24 * 60 * 60
TICKET_TTL_S = 30
TOKEN_BYTES = 32
RAW_NAME_MAX, NAME_MAX = 128, 32


def new_token() -> str:
    """32 random bytes in base64url without padding (43 characters)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def new_user_id() -> str:
    return f"u_{secrets.token_urlsafe(12)}"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def same_digest(stored: str, token: str) -> bool:
    return hmac.compare_digest(stored, digest(token))


def display_name(raw: str) -> str:
    """Trim and NFC-normalize; 1-32 characters after that, at most 128 before."""
    name = unicodedata.normalize("NFC", raw.strip())
    if len(raw) > RAW_NAME_MAX or not 1 <= len(name) <= NAME_MAX:
        raise DomainError(ErrorCode.INVALID_MESSAGE, "displayName must be 1-32 characters")
    return name
