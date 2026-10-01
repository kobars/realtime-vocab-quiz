# AI-ASSISTED: the settings defaults of docs/spec/protocol.md and their environment overrides.
from ipaddress import ip_network

import pytest
from pydantic import ValidationError

from quiz.config import Settings

ENV_NAMES = (
    *("STORE", "REDIS_URL", "NODE_ID", "TICK_MS", "TOP_N", "FULL_LIST_MAX", "MAX_PAYLOAD_BYTES"),
    *("HEARTBEAT_MS", "SEND_BUFFER_SOFT_BYTES", "SEND_BUFFER_HARD_BYTES", "GRACE_MS"),
    *("RATE_LIMIT_PER_S", "RATE_LIMIT_BURST", "ALLOWED_ORIGINS", "QUIZ_PORT", "PER_IP_CONN_CAP"),
    *("MAX_CONNECTIONS", "TRUSTED_PROXIES", "ADMIN_MOCK", "ADMIN_TOKEN"),
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_the_spec() -> None:
    s = Settings()
    assert (s.store, s.redis_url) == ("memory", "redis://127.0.0.1:6381/0")
    assert (s.tick_ms, s.top_n, s.full_list_max) == (200, 50, 200)
    assert (s.max_payload_bytes, s.heartbeat_ms, s.grace_ms) == (16 * 1024, 25_000, 10_000)
    assert (s.send_buffer_soft_bytes, s.send_buffer_hard_bytes) == (64 * 1024, 256 * 1024)
    assert (s.rate_limit_per_s, s.rate_limit_burst) == (20, 40)
    assert (s.per_ip_conn_cap, s.max_connections) == (50, 10_000)
    assert s.allowed_origins == ("http://localhost:8080", "http://127.0.0.1:8080")
    assert s.trusted_proxies == (ip_network("172.16.0.0/12"),)
    assert s.node_id
    assert (s.admin_mock, s.admin_token) == (False, None)


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"STORE": "redis", "PER_IP_CONN_CAP": "1000", "QUIZ_PORT": "9000", "NODE_ID": "api-1"}
    env |= {"TRUSTED_PROXIES": "10.0.0.0/8, 192.168.5.7", "ADMIN_MOCK": "1", "ADMIN_TOKEN": "t"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    s = Settings()
    assert (s.store, s.per_ip_conn_cap, s.node_id, s.admin_mock) == ("redis", 1000, "api-1", True)
    assert s.allowed_origins == ("http://localhost:9000", "http://127.0.0.1:9000")
    assert s.trusted_proxies == (ip_network("10.0.0.0/8"), ip_network("192.168.5.7/32"))
    assert s.admin_token is not None
    assert s.admin_token.get_secret_value() == "t"


def test_explicit_origins_replace_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173,https://quiz.example")
    assert Settings().allowed_origins == ("http://localhost:5173", "https://quiz.example")


@pytest.mark.parametrize(
    "fields",
    [
        {"store": "postgres"},
        {"top_n": 51},  # the leaderboard frame holds at most 50 entries
        {"full_list_max": 201},
        {"top_n": 40, "full_list_max": 30},
        {"send_buffer_soft_bytes": 256 * 1024},  # soft must stay below hard
        {"rate_limit_per_s": 50, "rate_limit_burst": 40},
        {"tick_ms": 0},
        {"admin_mock": True},  # the mock admin endpoints need a token
    ],
)
def test_invalid_settings_are_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(fields)
