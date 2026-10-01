# AI-ASSISTED: guard that the pure domain package imports only the standard library.
import ast
import importlib.util
import sys
from pathlib import Path

import quiz.domain

DOMAIN = Path(quiz.domain.__file__).parent


def _resolve(node: ast.ImportFrom, package: str) -> str:
    name = "." * node.level + (node.module or "")
    try:
        return importlib.util.resolve_name(name, package)
    except ImportError:  # climbs above the top-level package
        return name


def _imported_modules(source: str, package: str) -> set[str]:
    """Return the absolute modules that ``source``, a module of ``package``, imports."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node, package)
            if node.module or node.level == 0:
                modules.add(base)
            else:  # "from .. import app" may import the submodule quiz.app
                modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def _package(path: Path) -> str:
    return ".".join(path.parent.relative_to(DOMAIN.parent.parent).parts)


def _allowed(module: str) -> bool:
    return module.partition(".")[0] in sys.stdlib_module_names or (
        module == "quiz.domain" or module.startswith("quiz.domain.")
    )


def test_domain_imports_only_the_standard_library() -> None:
    files = sorted(DOMAIN.rglob("*.py"))
    assert len(files) > 1
    outside = {
        f"{path.name}: {module}"
        for path in files
        for module in _imported_modules(path.read_text(encoding="utf-8"), _package(path))
        if not _allowed(module)
    }
    assert outside == set()


def test_guard_flags_third_party_and_other_quiz_packages() -> None:
    source = "import redis\nfrom quiz.adapters import x\nfrom fractions import Fraction\n"
    flagged = {m for m in _imported_modules(source, "quiz.domain") if not _allowed(m)}
    assert flagged == {"redis", "quiz.adapters"}


def test_guard_resolves_relative_imports() -> None:
    source = (
        "from .scoring import points\nfrom . import standings\n"
        "from ..adapters import redis_store\nfrom .. import app\n"
    )
    flagged = {m for m in _imported_modules(source, "quiz.domain") if not _allowed(m)}
    assert flagged == {"quiz.adapters", "quiz.app"}
