# AI-ASSISTED: checks on the pre-commit hooks, make targets, deptry and the CI workflows.
"""Tests for the repository's hook and workflow configuration.

The workflows and the Makefile are read as text; the hook test uses pre-commit's own
config loader.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from pre_commit.clientlib import load_config

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


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


def _hook(hook_id: str) -> dict[str, object]:
    """Return one hook of the pre-commit config, with pre-commit's defaults filled in."""
    config = load_config(str(ROOT / ".pre-commit-config.yaml"))
    specs: list[dict[str, object]] = [
        h for repo in config["repos"] for h in repo["hooks"] if h["id"] == hook_id
    ]
    (spec,) = specs
    return spec


def _run_commands(path: Path) -> list[str]:
    """Return the command of every one-line ``run:`` step of a workflow."""
    text = path.read_text(encoding="utf-8")
    lines = (line.strip().removeprefix("- ") for line in text.splitlines())
    return [line.removeprefix("run:").strip() for line in lines if line.startswith("run:")]


def test_eslint_hook_runs_one_process_so_the_typescript_program_is_built_once() -> None:
    assert _hook("eslint")["require_serial"] is True


GATE_FAILS = "- if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')"


@pytest.mark.parametrize(
    ("workflow", "gate", "needs"),
    [
        ("ci.yml", "ci-required", "[check, integration, guards, review-budget]"),
        ("security.yml", "security-required", "[secrets, dependency-review]"),
        ("containers.yml", "containers-required", "[config, images]"),
    ],
)
def test_each_workflow_has_one_gate_job_over_its_required_jobs(
    workflow: str, gate: str, needs: str
) -> None:
    # The ruleset requires the gate job ids, so a rename or a dropped need shows up here.
    job = _section(WORKFLOWS / workflow, gate, 2)
    assert f"needs: {needs}" in job
    assert "if: always()" in job
    assert GATE_FAILS in job
    assert not any(line.startswith("name:") for line in job)


@pytest.mark.parametrize(
    ("workflow", "types"),
    [
        # ci.yml runs again on a label change, for the guards; never on a PR text edit.
        ("ci.yml", ["types: [opened, synchronize, reopened, labeled, unlabeled]"]),
        ("containers.yml", []),
    ],
)
def test_workflow_runs_on_every_pull_request_update_and_on_main(
    workflow: str, types: list[str]
) -> None:
    on = _section(WORKFLOWS / workflow, "on", 0)
    assert "pull_request:" in on
    assert [line for line in on if line.startswith("types:")] == types
    assert on[on.index("push:") + 1] == "branches: [main]"


@pytest.mark.parametrize("job", ["guards", "review-budget"])
def test_pull_request_checks_read_the_whole_history_of_the_pr_head(job: str) -> None:
    lines = _section(WORKFLOWS / "ci.yml", job, 2)
    assert "if: github.event_name == 'pull_request'" in lines
    assert "ref: ${{ github.event.pull_request.head.sha }}" in lines
    assert "fetch-depth: 0" in lines


@pytest.mark.parametrize("workflow", ["ci.yml", "security.yml", "containers.yml", "codeql.yml"])
def test_only_a_newer_pull_request_run_cancels_an_older_one(workflow: str) -> None:
    concurrency = _section(WORKFLOWS / workflow, "concurrency", 0)
    group = "group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}"
    assert group in concurrency
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in concurrency


def test_container_workflow_runs_every_infra_check_on_pull_requests() -> None:
    path = WORKFLOWS / "containers.yml"
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
    probe.write_text("import httpcore\nimport no_such_package\nimport pydantic_core\n")
    _, flags = _deptry_tools()
    config = str(ROOT / "api" / "pyproject.toml")
    result = _deptry("tests", *flags, "--config", config, cwd=tmp_path)
    assert result.returncode == 1
    assert "DEP001 'no_such_package' imported but missing" in result.stderr
    assert "DEP003 'httpcore' imported but it is a transitive dependency" in result.stderr
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


def _phony_and_targets(makefile: str) -> tuple[list[str], list[str]]:
    """Return the sorted ``.PHONY`` names and the sorted names of the defined targets."""
    phony = re.search(r"^\.PHONY:(.*)$", makefile, re.MULTILINE)
    assert phony is not None
    targets = re.findall(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?!=)", makefile, re.MULTILINE)
    return sorted(phony.group(1).split()), sorted(targets)


def test_target_names_with_digits_underscores_and_dots_are_found() -> None:
    makefile = ".PHONY: e2e\nVAR := 1\nV2:=2\ne2e: ## a\n\techo\nlint_py.v2: ## b\n\techo\n"
    assert _phony_and_targets(makefile) == (["e2e"], ["e2e", "lint_py.v2"])


def test_every_make_target_is_phony_and_none_is_a_placeholder() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    phony, targets = _phony_and_targets(makefile)
    assert phony == targets
    assert "not yet" not in makefile
