# AI-ASSISTED: checks that make audit-secrets refuses to pass when it cannot see the whole history.
"""Tests for the full-history guard of ``make audit-secrets``.

gitleaks exits 0 with "no leaks found" outside a git repository and scans only the
fetched commits of a shallow clone, so the target must fail before gitleaks runs.
The guard fails first, so these tests need no gitleaks binary.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _audit_secrets(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``make audit-secrets`` in ``cwd`` with no git variables inherited from a hook."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    return subprocess.run(
        ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "audit-secrets"],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_fails_outside_a_git_repository(tmp_path: Path) -> None:
    result = _audit_secrets(tmp_path)
    assert result.returncode != 0
    assert "the secret scan needs the whole history" in result.stderr


def test_fails_in_a_shallow_clone(tmp_path: Path) -> None:
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", ROOT.as_uri(), str(shallow)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    result = _audit_secrets(shallow)
    assert result.returncode != 0
    assert "the secret scan needs the whole history" in result.stderr
