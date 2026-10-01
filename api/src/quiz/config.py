# AI-ASSISTED: the service settings, read from environment variables, with the spec's defaults.
"""Every tunable of the service. Each field reads the environment variable of its name in upper
case (``per_ip_conn_cap`` from ``PER_IP_CONN_CAP``); lists are comma-separated."""

import os
import socket
from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from quiz.contracts.codec import MAX_FRAME_BYTES
from quiz.contracts.messages import FULL_LIST_MAX, TOP_N

KIB = 1024
# The local host only: a proxy elsewhere (nginx on the compose network) is named by its address or
# its network's subnet, never by a whole private range that clients may share with it.
LOCAL_PROXIES = ("127.0.0.1/32", "::1/128")


def _default_node_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    store: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:6381/0"
    # A burst above the pool's size waits this long for a free connection, then UNAVAILABLE.
    # Each quiz this process serves holds one connection for its subscription.
    redis_max_connections: PositiveInt = 100
    redis_pool_timeout_ms: PositiveInt = 2_000
    node_id: Annotated[str, Field(min_length=1, max_length=64)] = Field(
        default_factory=_default_node_id
    )

    tick_ms: PositiveInt = 200  # the coalescing tick, only while the quiz is dirty
    top_n: Annotated[int, Field(ge=1, le=TOP_N)] = TOP_N
    full_list_max: Annotated[int, Field(ge=1, le=FULL_LIST_MAX)] = FULL_LIST_MAX
    # At most the parser's limit, so every frame above it closes with 1009.
    max_payload_bytes: Annotated[int, Field(ge=1, le=MAX_FRAME_BYTES)] = MAX_FRAME_BYTES
    heartbeat_ms: PositiveInt = 25_000
    send_buffer_soft_bytes: PositiveInt = 64 * KIB  # above it: skip and conflate leaderboards
    send_buffer_hard_bytes: PositiveInt = 256 * KIB  # above it: error, then close 1013
    grace_ms: PositiveInt = 10_000  # after a disconnect, before the player counts as gone
    rate_limit_per_s: PositiveInt = 20  # the per-connection token bucket
    rate_limit_burst: PositiveInt = 40

    quiz_port: Annotated[int, Field(ge=1, le=65_535)] = 8080  # the public entry (nginx)
    # Empty: http://localhost and http://127.0.0.1 on QUIZ_PORT.
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(default=(), validate_default=True)
    max_connections: PositiveInt = 10_000  # per process; above it HTTP 503 at the upgrade
    per_ip_conn_cap: PositiveInt = 50  # above it HTTP 429; raised for the demo and load runs
    # X-Forwarded-For is trusted only from these peers.
    trusted_proxies: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = tuple(
        ip_network(proxy) for proxy in LOCAL_PROXIES
    )

    admin_mock: bool = False  # MOCK: the quiz admin endpoints exist only when set
    admin_token: SecretStr | None = None

    @field_validator("allowed_origins", "trusted_proxies", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _default_origins(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        if value or "quiz_port" not in info.data:
            return value
        return tuple(
            f"http://{host}:{info.data['quiz_port']}" for host in ("localhost", "127.0.0.1")
        )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.top_n > self.full_list_max:
            msg = "TOP_N must not exceed FULL_LIST_MAX"
            raise ValueError(msg)
        if self.send_buffer_soft_bytes >= self.send_buffer_hard_bytes:
            msg = "SEND_BUFFER_SOFT_BYTES must be below SEND_BUFFER_HARD_BYTES"
            raise ValueError(msg)
        if self.rate_limit_burst < self.rate_limit_per_s:
            msg = "RATE_LIMIT_BURST must be at least RATE_LIMIT_PER_S"
            raise ValueError(msg)
        token = "" if self.admin_token is None else self.admin_token.get_secret_value()
        if self.admin_mock and not token.strip():
            msg = "ADMIN_MOCK needs a non-blank ADMIN_TOKEN"
            raise ValueError(msg)
        return self
