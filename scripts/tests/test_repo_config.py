# AI-ASSISTED: checks on the pre-commit hooks and the CI workflow triggers.
"""Tests for the repository's hook and workflow configuration.

The files are read as text, so the tests need no YAML library.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _block(path: Path, start: str, next_prefix: str) -> list[str]:
    """Return the stripped lines from the line equal to ``start`` up to the next ``next_prefix``."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    begin = lines.index(start)
    end = next(
        (i for i in range(begin + 1, len(lines)) if lines[i].startswith(next_prefix)),
        len(lines),
    )
    return lines[begin:end]


def _job(name: str) -> list[str]:
    """Return the stripped lines of one job of the CI workflow."""
    path = ROOT / ".github" / "workflows" / "ci.yml"
    raw = path.read_text(encoding="utf-8").splitlines()
    begin = raw.index(f"  {name}:")
    end = next(
        (i for i in range(begin + 1, len(raw)) if raw[i].startswith("  ") and raw[i][2] != " "),
        len(raw),
    )
    return [line.strip() for line in raw[begin:end]]


def test_internal_hook_scans_every_staged_file() -> None:
    hook = _block(ROOT / ".pre-commit-config.yaml", "- id: check-internal", "- id:")
    filters = ("types:", "types_or:", "files:", "exclude:", "exclude_types:")
    assert [line for line in hook if line.startswith(filters)] == []


def test_ci_runs_again_when_the_pull_request_text_is_edited() -> None:
    trigger = _block(ROOT / ".github" / "workflows" / "ci.yml", "pull_request:", "permissions:")
    assert "types: [opened, synchronize, reopened, edited]" in trigger


def test_only_the_internal_job_runs_on_an_edit() -> None:
    skip_edit = "if: github.event.action != 'edited'"
    assert skip_edit in _job("check")
    assert skip_edit in _job("integration")
    assert skip_edit not in _job("internal")
