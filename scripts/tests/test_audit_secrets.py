# AI-ASSISTED: checks the full-history guard of make audit-secrets and its scan of the HEAD history.
"""Tests for ``make audit-secrets``.

gitleaks exits 0 with "no leaks found" outside a git repository and scans only the
fetched commits of a shallow clone, so the target must fail before gitleaks runs.
The guard fails first, so those tests need no gitleaks binary.

By default gitleaks scans ``git log --all``. A CI checkout with the whole history
fetches every branch, so one branch's secret would fail every other pull request.
The target scans only the commits reachable from HEAD: on a pull request that is the
merge commit, so everything that would land is still scanned.
"""

import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _audit_secrets(cwd: Path, path: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``make audit-secrets`` in ``cwd`` with no git variables inherited from a hook."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "audit-secrets"],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo_with_secret_on_branch(tmp_path: Path) -> Path:
    """A full repository: a clean ``main`` checked out and a secret on the branch ``other``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "other")
    # Built at run time, so this file holds no token for the repository's own scan.
    (repo / "token.txt").write_text(f'token = "ghp_{secrets.token_hex(18)}"\n')
    _git(repo, "add", "token.txt")
    _git(repo, "commit", "-q", "-m", "add token")
    _git(repo, "checkout", "-q", "main")
    return repo


def test_fails_outside_a_git_repository(tmp_path: Path) -> None:
    result = _audit_secrets(tmp_path)
    assert result.returncode != 0
    assert "the secret scan needs the whole history" in result.stderr


def test_fails_in_a_shallow_clone(tmp_path: Path) -> None:
    """A throwaway origin, so the test runs where the checkout has no history (the test image)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    for message in ("first", "second"):
        _git(origin, "commit", "-q", "--allow-empty", "-m", message)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", origin.as_uri(), str(shallow)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    result = _audit_secrets(shallow)
    assert result.returncode != 0
    assert "the secret scan needs the whole history" in result.stderr


def test_passes_gitleaks_the_history_of_head_only(tmp_path: Path) -> None:
    repo = _repo_with_secret_on_branch(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "gitleaks-args"
    stub = bin_dir / "gitleaks"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{args_file}"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    result = _audit_secrets(repo, path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    assert result.returncode == 0, result.stderr
    assert "--log-opts=--full-history HEAD" in args_file.read_text().splitlines()


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="needs gitleaks on the PATH")
def test_ignores_a_secret_on_another_branch(tmp_path: Path) -> None:
    repo = _repo_with_secret_on_branch(tmp_path)
    assert _audit_secrets(repo).returncode == 0


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="needs gitleaks on the PATH")
def test_finds_a_secret_reachable_from_head(tmp_path: Path) -> None:
    repo = _repo_with_secret_on_branch(tmp_path)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge other", "other")
    assert _audit_secrets(repo).returncode != 0
