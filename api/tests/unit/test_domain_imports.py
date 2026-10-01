# AI-ASSISTED: guard that the pure domain package imports only the standard library.
import ast
import sys
from pathlib import Path

import quiz.domain

DOMAIN = Path(quiz.domain.__file__).parent


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


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
        for module in _imported_modules(path.read_text(encoding="utf-8"))
        if not _allowed(module)
    }
    assert outside == set()


def test_guard_flags_third_party_and_other_quiz_packages() -> None:
    source = "import redis\nfrom quiz.adapters import x\nfrom fractions import Fraction\n"
    flagged = {m for m in _imported_modules(source) if not _allowed(m)}
    assert flagged == {"redis", "quiz.adapters"}
