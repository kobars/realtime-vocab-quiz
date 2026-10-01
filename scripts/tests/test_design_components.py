# AI-ASSISTED: checks that DESIGN.md names every Lua script, route and mock setting.
"""DESIGN.md §4 and §14 must name what the specs and the settings define.

- The Store row of §4 names every script of the Redis spec's §3 (docs/spec/redis.md).
- The Gateway row of §4 names every HTTP endpoint of the protocol spec's §8.
- §14 names every setting that ``api/src/quiz/config.py`` marks ``MOCK:``.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "DESIGN.md"
REDIS_SPEC = ROOT / "docs" / "spec" / "redis.md"
PROTOCOL_SPEC = ROOT / "docs" / "spec" / "protocol.md"
CONFIG = ROOT / "api" / "src" / "quiz" / "config.py"


def section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def component_row(name: str) -> str:
    rows = [r for r in section(DESIGN, "## 4. ").splitlines() if r.startswith(f"| {name} (")]
    assert len(rows) == 1, f"DESIGN §4 has no single {name} row"
    return rows[0]


def redis_scripts() -> list[str]:
    text = section(REDIS_SPEC, "## 3. ")
    in_table = re.findall(r"^\| `([a-z_]+)` \|", text, re.MULTILINE)
    reads = re.findall(r"read-only script, `([a-z_]+)\(", text)
    assert in_table, "no script table in redis spec §3"
    assert reads, "no read-only script in redis spec §3"
    return in_table + reads


def http_paths() -> list[str]:
    text = section(PROTOCOL_SPEC, "## 8. ")
    paths = re.findall(r"`(?:GET|POST) (/[^\s`]+)", text)
    assert paths, "no HTTP endpoint table in protocol spec §8"
    return sorted(set(paths) - {"/ws?ticket=…"})


def mock_settings() -> list[str]:
    text = CONFIG.read_text(encoding="utf-8")
    names = re.findall(r"^    ([a-z_]+):.*#\s*MOCK:", text, re.MULTILINE)
    assert names, "no setting marked MOCK: in config.py"
    return [name.upper() for name in names]


@pytest.mark.parametrize("script", redis_scripts())
def test_store_row_names_every_redis_script(script: str) -> None:
    assert f"`{script}`" in component_row("Store")


@pytest.mark.parametrize("path", http_paths())
def test_gateway_row_names_every_http_endpoint(path: str) -> None:
    assert path in component_row("Gateway")


@pytest.mark.parametrize("setting", mock_settings())
def test_mocked_section_names_every_mock_setting(setting: str) -> None:
    assert f"`{setting}`" in section(DESIGN, "## 14. ")
