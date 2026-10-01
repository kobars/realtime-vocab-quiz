# AI-ASSISTED: tests for the contract drift check of scripts/gen_contracts.py.
"""Tests for ``gen_contracts.py --check`` against a throwaway git repository."""

import os
import subprocess
from pathlib import Path

import gen_contracts
import pytest


def git(cwd: Path, *args: str) -> None:
    """Run git isolated from the user's and the system's git configuration."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@noreply.invalid", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


def fake_write_types(_schema: Path, out: Path) -> None:
    """Stand in for json2ts, which needs the web toolchain."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("types\n")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose committed generated files match the generator's output."""
    schema = tmp_path / "contracts" / "protocol.json"
    types = tmp_path / "web" / "types.generated.ts"
    monkeypatch.setattr(gen_contracts, "ROOT", tmp_path)
    monkeypatch.setattr(gen_contracts, "SCHEMA", schema)
    monkeypatch.setattr(gen_contracts, "TYPES", types)
    monkeypatch.setattr(gen_contracts, "GENERATED", (schema, types))
    monkeypatch.setattr(gen_contracts, "write_types", fake_write_types)
    git(tmp_path, "init", "-q")
    assert gen_contracts.main([]) == 0
    (tmp_path / "README.md").write_text("readme\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "Add the generated files")
    return tmp_path


@pytest.mark.usefixtures("repo")
def test_check_passes_when_the_generated_files_match() -> None:
    assert gen_contracts.main(["--check"]) == 0


def test_check_ignores_changes_outside_the_generated_paths(repo: Path) -> None:
    (repo / "README.md").write_text("edited\n")
    (repo / "notes.txt").write_text("untracked\n")
    assert gen_contracts.main(["--check"]) == 0


def test_check_fails_on_a_stale_generated_file(repo: Path) -> None:
    gen_contracts.SCHEMA.write_text("{}\n")
    git(repo, "commit", "-q", "-am", "Edit the schema by hand")
    assert gen_contracts.main(["--check"]) == 1


def test_check_fails_when_a_generated_file_is_not_committed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `git diff --exit-code` passes here: the regenerated file is untracked, not changed.
    git(repo, "rm", "-q", str(gen_contracts.TYPES))
    git(repo, "commit", "-q", "-m", "Drop the types")
    assert gen_contracts.main(["--check"]) == 1
    assert "?? web/types.generated.ts" in capsys.readouterr().err


def test_drift_lists_changed_deleted_and_untracked_files(repo: Path) -> None:
    gen_contracts.SCHEMA.write_text("{}\n")
    gen_contracts.TYPES.unlink()
    extra = repo / "web" / "extra.ts"
    extra.write_text("new\n")
    lines = gen_contracts.drift(repo, (gen_contracts.SCHEMA, gen_contracts.TYPES, extra))
    assert sorted(lines) == [
        " D web/types.generated.ts",
        " M contracts/protocol.json",
        "?? web/extra.ts",
    ]
