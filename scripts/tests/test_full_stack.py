# AI-ASSISTED: checks on the compose full profile and the edge nginx config, read as files.
"""The full stack's hardening and edge rules, read from ``compose.yaml`` (with pre-commit's YAML
loader, which resolves the anchors) and ``infra/nginx/nginx.conf``; no Docker needed."""

import re
from pathlib import Path
from typing import Any

from pre_commit.yaml import yaml_load

from quiz.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE: dict[str, Any] = yaml_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
FULL = {name: s for name, s in COMPOSE["services"].items() if "full" in s.get("profiles", ())}
NGINX = (ROOT / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")


def _directive(name: str) -> list[str]:
    return re.findall(rf"^\s*{name} ([^;]+);", NGINX, re.MULTILINE)


def test_only_nginx_publishes_a_port_and_only_on_the_local_host() -> None:
    assert {name for name, s in FULL.items() if "ports" in s} == {"nginx"}
    assert FULL["nginx"]["ports"] == ["127.0.0.1:${QUIZ_PORT:-8080}:8080"]


def test_every_full_stack_service_is_hardened() -> None:
    assert set(FULL) == {"stack-redis", "api-1", "api-2", "web", "nginx"}
    for service in FULL.values():
        assert service["read_only"] is True
        assert service["tmpfs"] == ["/tmp"]  # noqa: S108 - a tmpfs inside the container
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["ulimits"] == {"nofile": 65536}


def test_two_api_nodes_with_distinct_ids_share_one_redis_and_trust_only_the_stack_network() -> None:
    nodes = [FULL["api-1"]["environment"], FULL["api-2"]["environment"]]
    assert [env["NODE_ID"] for env in nodes] == ["api-1", "api-2"]
    assert nodes[0] | {"NODE_ID": None} == nodes[1] | {"NODE_ID": None}
    assert nodes[0]["ADMIN_TOKEN"].startswith("${ADMIN_TOKEN:?")
    assert "${REDIS_PASSWORD:?" in nodes[0]["REDIS_URL"]
    (subnet,) = COMPOSE["networks"]["stack"]["ipam"]["config"]
    assert nodes[0]["TRUSTED_PROXIES"] == subnet["subnet"]


def test_the_access_log_never_records_the_query_string() -> None:
    (log_format,) = re.findall(r"log_format edge ([^;]+);", NGINX)
    assert "$uri" in log_format
    for variable in ("$request ", "$request_uri", "$args", "$query_string", "$http_referer"):
        assert variable not in log_format
    assert _directive("access_log") == ["/dev/stdout edge"]


def test_the_edge_holds_thousands_of_sockets_and_outlives_the_heartbeat() -> None:
    assert _directive("worker_rlimit_nofile") == ["65536"]
    assert _directive("worker_connections") == ["16384"]
    (timeout,) = _directive("proxy_read_timeout")
    assert int(timeout.removesuffix("s")) * 1000 > Settings.model_fields["heartbeat_ms"].default
    assert _directive("proxy_next_upstream") == ["error timeout http_503"]
    assert _directive("proxy_set_header X-Forwarded-For") == ["$remote_addr"]
