# AI-ASSISTED: checks on the pre-commit hooks, make check, deptry and the CI workflow triggers.
"""Tests for the repository's hook and workflow configuration.

The workflows and the Makefile are read as text; the hook test uses pre-commit's own
config loader and file filter.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from pre_commit.clientlib import load_config
from pre_commit.commands.run import Classifier
from pre_commit.hook import Hook
from pre_commit.prefix import Prefix

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


def _section(path: Path, key: str, indent: int) -> list[str]:
    """Return the stripped lines of the YAML key ``key`` written ``indent`` spaces deep, up to
    the next key at that depth or less."""
    raw = path.read_text(encoding="utf-8").splitlines()
    begin = raw.index(f"{' ' * indent}{key}:")
    end = next(
        (
            i
            for i in range(begin + 1, len(raw))
            if raw[i].strip() and len(raw[i]) - len(raw[i].lstrip()) <= indent
        ),
        len(raw),
    )
    return [line.strip() for line in raw[begin:end]]


def _job(name: str) -> list[str]:
    """Return the stripped lines of one job of the CI workflow."""
    return _section(ROOT / ".github" / "workflows" / "ci.yml", name, 2)


def _run_commands(path: Path) -> list[str]:
    """Return the command of every one-line ``run:`` step of a workflow."""
    text = path.read_text(encoding="utf-8")
    lines = (line.strip().removeprefix("- ") for line in text.splitlines())
    return [line.removeprefix("run:").strip() for line in lines if line.startswith("run:")]


def test_internal_hook_scans_every_staged_file_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pre-commit's own loader and file filter, so its default `types: [file]` applies.
    config = load_config(str(ROOT / ".pre-commit-config.yaml"))
    (spec,) = [h for repo in config["repos"] for h in repo["hooks"] if h["id"] == "check-internal"]
    hook = Hook.create(str(ROOT), Prefix(str(ROOT)), spec)
    monkeypatch.chdir(tmp_path)
    Path("notes.md").write_text("text\n", encoding="utf-8")
    Path(".hidden").write_text("text\n", encoding="utf-8")
    Path("link").symlink_to("notes.md")
    names = ["notes.md", ".hidden", "link"]
    assert sorted(Classifier(names).filenames_for_hook(hook)) == sorted(names)


def test_ci_runs_again_when_the_pull_request_text_is_edited() -> None:
    trigger = _block(ROOT / ".github" / "workflows" / "ci.yml", "pull_request:", "permissions:")
    assert "types: [opened, synchronize, reopened, edited]" in trigger


def test_only_the_internal_job_runs_on_an_edit() -> None:
    skip_edit = "if: github.event.action != 'edited'"
    assert skip_edit in _job("check")
    assert skip_edit in _job("integration")
    assert skip_edit not in _job("internal")


def test_container_workflow_runs_every_infra_check_on_pull_requests() -> None:
    path = ROOT / ".github" / "workflows" / "containers.yml"
    assert "pull_request:" in _section(path, "on", 0)
    runs = _run_commands(path)
    for command in (
        "hadolint/hadolint:",
        "xargs -0 --no-run-if-empty shellcheck",
        "docker compose -f {} config -q",
        "make build",
        'scripts/smoke_images.sh "$IMAGE_TAG"',
        'scripts/check_nginx.sh "$IMAGE_TAG"',
    ):
        assert any(command in run for run in runs), command
    workflow = path.read_text(encoding="utf-8")
    assert "scan-type: config" in workflow
    # Image scans fail on CRITICAL and HIGH findings that have a fix, for both images.
    assert workflow.count("ignore-unfixed: true") == workflow.count("image-ref:") == 2
    assert workflow.count("severity: CRITICAL,HIGH") == 2


def test_make_check_runs_every_pre_commit_hook_on_every_file() -> None:
    recipe = _block(
        ROOT / "Makefile", "check: ## Run every check a change must pass", "acceptance:"
    )
    assert any("pre-commit run --all-files" in line for line in recipe)


def _deptry_tools() -> tuple[list[str], list[str]]:
    """Return the roots and the flags of the Makefile's DEPTRY_TOOLS step."""
    line = next(
        line
        for line in (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
        if line.startswith("DEPTRY_TOOLS = ")
    )
    args = shlex.split(line.split(" deptry ", 1)[1])
    first_flag = next(i for i, arg in enumerate(args) if arg.startswith("-"))
    return args[:first_flag], args[first_flag:]


def _deptry(*args: str, cwd: Path = ROOT / "api") -> subprocess.CompletedProcess[str]:
    """Run deptry in ``cwd``; in api/ it reads api/pyproject.toml, as make check does."""
    return subprocess.run(
        [sys.executable, "-m", "deptry", *args, "--no-ansi"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_make_check_runs_the_dependency_check_on_every_python_root() -> None:
    recipe = _block(
        ROOT / "Makefile", "check: ## Run every check a change must pass", "acceptance:"
    )
    assert any("uv run --locked deptry src" in line for line in recipe)
    assert any("$(DEPTRY_TOOLS)" in line for line in recipe)
    roots, _ = _deptry_tools()
    assert roots == ["tests", "../scripts", "../load"]


def test_tool_dependency_check_fails_on_missing_and_transitive_imports(tmp_path: Path) -> None:
    # A folder named tests is skipped by deptry's default exclude; the step must still scan it.
    probe = tmp_path / "tests" / "test_probe.py"
    probe.parent.mkdir()
    probe.write_text("import anyio\nimport no_such_package\nimport pydantic_core\n")
    _, flags = _deptry_tools()
    config = str(ROOT / "api" / "pyproject.toml")
    result = _deptry("tests", *flags, "--config", config, cwd=tmp_path)
    assert result.returncode == 1
    assert "DEP001 'no_such_package' imported but missing" in result.stderr
    assert "DEP003 'anyio' imported but it is a transitive dependency" in result.stderr
    assert "pydantic_core" not in result.stderr


def test_dependency_check_fails_when_src_imports_pydantic_core(tmp_path: Path) -> None:
    # Only the tools step allows pydantic_core; the service code must not import it.
    probe = tmp_path / "src" / "quiz" / "probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("import pydantic_core\n")
    result = _deptry(str(tmp_path / "src"))
    assert result.returncode == 1
    assert "DEP003 'pydantic_core' imported but it is a transitive dependency" in result.stderr


def test_dependency_check_fails_when_a_direct_import_is_undeclared(tmp_path: Path) -> None:
    # src imports starlette directly; without its own entry it only arrives through fastapi.
    config, removed = re.subn(
        r'^\s*"starlette[^"]*",\n',
        "",
        (ROOT / "api" / "pyproject.toml").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert removed == 1
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")
    result = _deptry("src", "--config", str(tmp_path / "pyproject.toml"))
    assert result.returncode == 1
    assert "DEP003 'starlette' imported but it is a transitive dependency" in result.stderr
