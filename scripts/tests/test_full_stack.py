# AI-ASSISTED: checks on the compose full profile, its public-host override and the edge nginx
# config, read as files.
"""The full stack's hardening and edge rules, read from ``compose.yaml`` and ``compose.prod.yaml``
(with pre-commit's YAML loader, which resolves the anchors) and ``infra/nginx/nginx.conf``; no
Docker needed."""

import re
from pathlib import Path
from typing import Any

from pre_commit.yaml import yaml_load

from quiz.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE: dict[str, Any] = yaml_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
FULL = {name: s for name, s in COMPOSE["services"].items() if "full" in s.get("profiles", ())}
NGINX = (ROOT / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
PROD_TEXT = (ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
# pre-commit's loader knows no compose tags: read `!reset []` as the empty list it resets to.
PROD: dict[str, Any] = yaml_load(PROD_TEXT.replace("ports: !reset []", "ports: []"))


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


def test_every_full_stack_service_restarts_unless_it_was_stopped() -> None:
    """``make smoke-full`` stops a node with ``docker compose stop``, which the policy respects;
    the one-shot services (bots, seed, tests) stay finished."""
    assert {name: s.get("restart") for name, s in FULL.items()} == dict.fromkeys(
        FULL, "unless-stopped"
    )
    others = {name: s for name, s in COMPOSE["services"].items() if name not in FULL}
    assert [name for name, s in others.items() if "restart" in s] == []


def test_the_stack_redis_refuses_writes_when_full_instead_of_evicting_quiz_state() -> None:
    command = FULL["stack-redis"]["command"]
    flags = dict(zip(command[1::2], command[2::2], strict=True))
    assert flags["--maxmemory"] == "${REDIS_MAXMEMORY:-256mb}"
    assert flags["--maxmemory-policy"] == "noeviction"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# REDIS_MAXMEMORY=256mb ", example, re.MULTILINE)


def test_two_api_nodes_with_distinct_ids_share_one_redis_and_trust_only_the_stack_network() -> None:
    nodes = [FULL["api-1"]["environment"], FULL["api-2"]["environment"]]
    assert [env["NODE_ID"] for env in nodes] == ["api-1", "api-2"]
    assert nodes[0] | {"NODE_ID": None} == nodes[1] | {"NODE_ID": None}
    assert nodes[0]["ADMIN_TOKEN"].startswith("${ADMIN_TOKEN:?")
    redis_waits = ("REDIS_POOL_TIMEOUT_MS", "REDIS_SOCKET_TIMEOUT_MS", "REDIS_CONNECT_TIMEOUT_MS")
    for name in ("PER_IP_CONN_CAP", *redis_waits):
        assert nodes[0][name] is None  # passed through from .env, unset by default
    assert "${REDIS_PASSWORD:?" in nodes[0]["REDIS_URL"]
    (subnet,) = COMPOSE["networks"]["stack"]["ipam"]["config"]
    assert nodes[0]["TRUSTED_PROXIES"] == subnet["subnet"]


def test_the_nodes_take_the_redis_pool_size_from_env_with_the_settings_default() -> None:
    """Each quiz a node serves holds one subscription connection of a pool of this size."""
    pool = Settings.model_fields["redis_max_connections"].default
    for node in ("api-1", "api-2"):
        assert FULL[node]["environment"]["REDIS_MAX_CONNECTIONS"] == (
            f"${{REDIS_MAX_CONNECTIONS:-{pool}}}"
        )


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
    assert _directive("proxy_set_header X-Forwarded-For") == ["$remote_addr"]


def test_a_refused_upgrade_is_not_replayed_and_a_503_takes_no_node_out() -> None:
    """The node redeems the single-use ticket before its caps answer 503."""
    (ws,) = re.findall(r"location = /ws \{(.*?)\n        \}", NGINX, re.DOTALL)
    assert _directive("proxy_next_upstream") == ["error timeout http_503", "error timeout"]
    assert "proxy_next_upstream error timeout;" in ws
    assert _directive("server api-[12]:8000") == ["resolve max_fails=0"] * 2


def test_the_edge_ceilings_hold_for_the_whole_stack_behind_any_proxy() -> None:
    """Behind Caddy, $remote_addr names each client: the zones key on one constant instead, so
    they stay stack-wide ceilings, and the nodes limit each address."""
    assert re.search(r'map "" \$whole_stack \{\s*default stack;\s*\}', NGINX)
    assert _directive("limit_req_zone") == ["$whole_stack zone=identity:10m rate=1000r/s"]
    assert _directive("limit_conn_zone") == ["$whole_stack zone=api_conn:10m"]


def test_the_identity_rate_limit_lets_a_load_run_join() -> None:
    """The ceiling holds for the whole stack: 5,000 sockets, a session and a ticket each."""
    (rate,) = re.findall(r"zone=identity:10m rate=(\d+)r/s", NGINX)
    for burst in re.findall(r"limit_req zone=identity burst=(\d+) nodelay", NGINX):
        assert int(burst) + 10 * int(rate) >= 2 * 5_000


def test_the_edge_cuts_slow_requests_and_caps_the_api_requests_in_flight() -> None:
    """The cap holds for the whole stack: above the bot swarm's 100 HTTP connections per process
    at 10 processes."""
    assert _directive("client_header_timeout") == ["10s"]
    assert _directive("client_body_timeout") == ["10s"]
    (api,) = re.findall(r"location /api/ \{(.*?)\n        \}", NGINX, re.DOTALL)
    (cap,) = re.findall(r"^            limit_conn api_conn (\d+);", api, re.MULTILINE)
    assert int(cap) >= 10 * 100
    assert _directive("limit_conn api_conn") == [cap]  # never on /ws, whose sockets the nodes cap


def test_the_edge_drops_a_stalled_reader_but_leaves_a_socket_to_its_node() -> None:
    """A socket whose client stops reading misses its pong: its node drops it within two
    heartbeats, before nginx's write timeout on that socket."""
    (ws,) = re.findall(r"location = /ws \{(.*?)\n        \}", NGINX, re.DOTALL)
    assert _directive("send_timeout") == ["10s", "60s"]
    (timeout,) = re.findall(r"^\s*send_timeout (\d+)s;", ws, re.MULTILINE)
    assert int(timeout) * 1000 > 2 * Settings.model_fields["heartbeat_ms"].default


def test_a_node_redirect_stays_under_the_api_prefix_and_port() -> None:
    assert _directive("proxy_set_header Host") == ["$http_host"]
    assert _directive("proxy_redirect") == ["http://$http_host/ /api/"]


def test_the_example_env_leaves_both_secrets_empty() -> None:
    """compose's .env parser reads a comment after an empty value as the value."""
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "ADMIN_TOKEN=" in lines
    assert "REDIS_PASSWORD=" in lines


def test_make_down_stops_every_profile() -> None:
    """``docker compose down`` without a profile leaves profiled services running."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\n\t$(COMPOSE_NO_SECRETS) --profile '*' down\n" in makefile


def test_on_a_public_host_only_caddy_publishes_a_port_80_and_443() -> None:
    services = PROD["services"]
    assert services["caddy"]["ports"] == ["80:80", "443:443"]
    assert "ports: !reset []" in PROD_TEXT
    assert services["nginx"]["ports"] == []
    assert [name for name, s in services.items() if s.get("ports")] == ["caddy"]


def test_caddy_is_hardened_and_never_on_the_stack_network() -> None:
    caddy = PROD["services"]["caddy"]
    for key in ("read_only", "tmpfs", "cap_drop", "security_opt", "ulimits", "restart"):
        assert caddy[key] == FULL["nginx"][key]
    assert caddy["cap_add"] == ["NET_BIND_SERVICE"]
    assert caddy["user"].split(":")[0] not in ("", "0", "root")  # the image's default is root
    assert caddy["networks"] == ["edge"]  # apart from Redis and the API nodes
    assert PROD["services"]["nginx"]["networks"] == ["stack", "edge"]


def test_nginx_trusts_x_forwarded_for_from_the_edge_network_only() -> None:
    """The image's entrypoint renders templates/edge/ into NGINX_ENVSUBST_OUTPUT_DIR/edge/."""
    nginx = PROD["services"]["nginx"]
    (edge,) = PROD["networks"]["edge"]["ipam"]["config"]
    assert nginx["environment"]["EDGE_SUBNET"] == edge["subnet"]
    template = (ROOT / "infra" / "nginx" / "real-ip.conf.template").read_text(encoding="utf-8")
    assert re.findall(r"^(\w+) ([^;]+);", template, re.MULTILINE) == [
        ("set_real_ip_from", "${EDGE_SUBNET}"),
        ("real_ip_header", "X-Forwarded-For"),
    ]
    (mount,) = nginx["volumes"]
    assert (
        mount
        == "./infra/nginx/real-ip.conf.template:/etc/nginx/templates/edge/real-ip.conf.template:ro"
    )
    assert f"{nginx['environment']['NGINX_ENVSUBST_OUTPUT_DIR']}/edge/*.conf" in _directive(
        "include"
    )


def test_on_a_public_host_the_nodes_allow_the_public_origin_from_env() -> None:
    for node in ("api-1", "api-2"):
        assert PROD["services"][node]["environment"] == {
            "ALLOWED_ORIGINS": "${ALLOWED_ORIGINS:?set ALLOWED_ORIGINS in .env}"
        }
    assert PROD["services"]["seed"]["command"][-2:] == [
        "--public-url",
        "https://${DOMAIN:?set DOMAIN in .env}",
    ]


def test_the_public_host_example_env_names_the_origin_and_the_default_cap() -> None:
    lines = (ROOT / ".env.prod.example").read_text(encoding="utf-8").splitlines()
    env = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    assert env["ALLOWED_ORIGINS"] == "https://${DOMAIN}"
    assert env["ADMIN_TOKEN"] == env["REDIS_PASSWORD"] == ""  # a comment would be the value
    assert int(env["PER_IP_CONN_CAP"]) == Settings.model_fields["per_ip_conn_cap"].default
    # Plain `docker compose`, make new-quiz's and make down's included, then acts on the HTTPS
    # stack, on the published images of main.
    assert env["COMPOSE_FILE"] == "compose.yaml:compose.prod.yaml:compose.images.yaml"
    assert env["IMAGE_TAG"] == "main"
    assert re.fullmatch(r"\d+[mg]b", env["REDIS_MAXMEMORY"])


def test_the_public_host_targets_run_the_compose_files_of_the_deploy_script() -> None:
    """scripts/deploy/ops.sh compose runs both files, plus compose.images.yaml when IMAGE_TAG is
    set (scripts/tests/test_deploy.py)."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\nPROD_COMPOSE = scripts/deploy/ops.sh compose\n" in makefile
    for target in ("prod-down", "prod-logs", "prod-demo"):
        recipe = re.search(rf"^{target}:.*\n\t(.*)", makefile, re.MULTILINE)
        assert recipe is not None
        assert recipe[1].startswith("$(PROD_COMPOSE) ")
    assert re.search(r"^prod-up:.*\n\tscripts/deploy/ops\.sh up\n", makefile, re.MULTILINE)


def test_prod_up_recreates_the_edge_so_a_pulled_config_change_applies() -> None:
    """git replaces a changed file, and a running container keeps the old bind-mounted one."""
    ops = (ROOT / "scripts" / "deploy" / "ops.sh").read_text(encoding="utf-8")
    (body,) = re.findall(r"^up\(\) \{\n(.*?)^\}", ops, re.MULTILINE | re.DOTALL)
    assert body.splitlines()[-1].endswith("--no-deps --force-recreate nginx caddy")


def test_the_published_images_replace_every_image_built_here() -> None:
    images = yaml_load((ROOT / "compose.images.yaml").read_text(encoding="utf-8"))["services"]
    built_here = {
        name: s["image"]
        for name, s in COMPOSE["services"].items()
        if s.get("image", "").startswith(("elsaquiz-api:", "elsaquiz-web:"))
    }
    assert images.keys() == built_here.keys()
    for name, image in built_here.items():
        repo = image.split(":")[0].replace("elsaquiz-", "ghcr.io/kobars/realtime-vocab-quiz-")
        assert images[name] == {"image": f"{repo}:${{IMAGE_TAG:-main}}"}


def test_caddy_keeps_the_admin_token_and_the_socket_ticket_out_of_its_logs() -> None:
    """A failed upstream request is logged with its headers and URI; Caddy redacts only
    Authorization and cookies by itself."""
    caddyfile = (ROOT / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    global_options = caddyfile[caddyfile.index("\n{\n") : caddyfile.index("\n}\n")]
    assert re.search(r"^\t\tformat filter \{", global_options, re.MULTILINE)
    assert "request>headers>X-Admin-Token delete" in global_options
    assert re.search(r"request>uri query \{\s*replace ticket REDACTED\s*\}", global_options)


def test_the_https_ci_job_starts_from_the_example_env() -> None:
    """Its .env is the shipped example, whose COMPOSE_FILE every docker compose call there uses."""
    stack = (ROOT / ".github" / "workflows" / "stack.yml").read_text(encoding="utf-8")
    (prod,) = re.findall(r"^  prod:\n(.*?)\n  [a-z-]+:\n", stack, re.DOTALL | re.MULTILINE)
    assert "cp .env.prod.example .env" in prod
    assert " -f compose" not in prod  # COMPOSE_FILE from the example's .env
