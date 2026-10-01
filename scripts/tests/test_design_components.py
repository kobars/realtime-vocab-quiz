# AI-ASSISTED: checks that DESIGN.md names every Lua script, route, mock setting and requirement.
"""DESIGN.md §4 and §14 must name what the specs and the settings define.

- The Store row of §4 names every script of the Redis spec's §3 (docs/spec/redis.md).
- The Gateway row of §4 names every HTTP endpoint of the protocol spec's §8.
- §14 names every setting that ``api/src/quiz/config.py`` marks ``MOCK:``.
- Every requirement ID in a section heading is a row of docs/TRACEABILITY.md
  whose evidence is not the video, since the video is not in DESIGN.md.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "DESIGN.md"
REDIS_SPEC = ROOT / "docs" / "spec" / "redis.md"
PROTOCOL_SPEC = ROOT / "docs" / "spec" / "protocol.md"
CONFIG = ROOT / "api" / "src" / "quiz" / "config.py"
TRACEABILITY = ROOT / "docs" / "TRACEABILITY.md"


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


def heading_tags() -> list[str]:
    text = DESIGN.read_text(encoding="utf-8")
    groups = re.findall(r"^## \d+\. .*\(([A-Z]+-\d+(?:, [A-Z]+-\d+)*)\)$", text, re.MULTILINE)
    assert groups, "no requirement IDs in the DESIGN headings"
    return [tag for group in groups for tag in group.split(", ")]


def evidence_types() -> dict[str, str]:
    text = TRACEABILITY.read_text(encoding="utf-8")
    return dict(re.findall(r"^\| ([A-Z]+-\d+) \|[^|]*\| (\w+) \|", text, re.MULTILINE))


@pytest.mark.parametrize("script", redis_scripts())
def test_store_row_names_every_redis_script(script: str) -> None:
    assert f"`{script}`" in component_row("Store")


@pytest.mark.parametrize("path", http_paths())
def test_gateway_row_names_every_http_endpoint(path: str) -> None:
    assert path in component_row("Gateway")


@pytest.mark.parametrize("setting", mock_settings())
def test_mocked_section_names_every_mock_setting(setting: str) -> None:
    assert f"`{setting}`" in section(DESIGN, "## 14. ")


@pytest.mark.parametrize("tag", heading_tags())
def test_heading_tags_are_written_requirements(tag: str) -> None:
    evidence = evidence_types().get(tag)
    assert evidence is not None, f"{tag} is not a row of docs/TRACEABILITY.md"
    assert evidence != "video", f"{tag} is a video requirement, not a DESIGN section"
