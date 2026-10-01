# AI-ASSISTED: guard that the pure domain package imports only the standard library and keeps
# no global state.
import ast
import importlib.util
import sys
from pathlib import Path

import quiz.domain

DOMAIN = Path(quiz.domain.__file__).parent
CLOCK_AND_IO = {
    *("time", "datetime", "random", "uuid", "secrets", "os", "io", "pathlib", "sys"),
    *("shutil", "tempfile", "subprocess", "signal", "select", "selectors", "socket", "ssl"),
    *("asyncio", "threading", "multiprocessing", "concurrent", "http", "urllib", "sqlite3"),
    *("logging", "importlib"),
}
MUTABLE_FACTORIES = {"dict", "list", "set", "defaultdict", "OrderedDict", "Counter", "deque"}
CACHES = {"cache", "lru_cache"}


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
    top = module.partition(".")[0]
    return (top in sys.stdlib_module_names and top not in CLOCK_AND_IO) or (
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


def _name(node: ast.expr) -> str:
    """The last name of ``f``, ``m.f`` or ``f(...)``."""
    node = node.func if isinstance(node, ast.Call) else node
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def _is_mutable(value: ast.expr | None) -> bool:
    containers = ast.Dict | ast.List | ast.Set | ast.DictComp | ast.ListComp | ast.SetComp
    return isinstance(value, containers) or (
        isinstance(value, ast.Call) and _name(value) in MUTABLE_FACTORIES
    )


def _is_final_constant(node: ast.stmt) -> bool:
    if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
        return False
    hint = node.annotation.value if isinstance(node.annotation, ast.Subscript) else node.annotation
    return node.target.id.isupper() and _name(hint) == "Final"


def _global_state(source: str) -> set[str]:
    """Return the module-level mutable bindings, caches and global statements in ``source``."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        if _is_mutable(value) and not _is_final_constant(node):
            found.add(f"mutable binding at line {node.lineno}")
    for item in ast.walk(tree):
        if isinstance(item, ast.Global | ast.Nonlocal):
            found.add(f"{type(item).__name__.lower()} at line {item.lineno}")
        elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            found.update(
                f"{_name(d)} at line {d.lineno}" for d in item.decorator_list if _name(d) in CACHES
            )
    return found


def test_domain_keeps_no_global_state() -> None:
    found = {
        f"{path.name}: {item}"
        for path in DOMAIN.rglob("*.py")
        for item in _global_state(path.read_text(encoding="utf-8"))
    }
    assert found == set()


def test_guard_flags_module_level_mutable_state_and_caches() -> None:
    source = (
        "import functools\nfrom collections import defaultdict\nfrom typing import Final\n"
        "_SEEN = {}\nNAMES: list[str] = []\nBY_USER = defaultdict(list)\nIDS = set()\n"
        "LIMITS: Final = {'a': 1}\nVIEW = MappingProxyType({})\nKEYS = frozenset({1})\n"
        "PAIR = tuple([1, 2])\nlower: Final = {}\n"
        "@functools.cache\ndef f(): ...\n@lru_cache(maxsize=8)\ndef g(): ...\n"
        "def h():\n    global _SEEN\n    _SEEN[1] = 2\n"
    )
    assert _global_state(source) == {
        *(f"mutable binding at line {n}" for n in (4, 5, 6, 7, 12)),
        "cache at line 13",
        "lru_cache at line 15",
        "global at line 18",
    }


def test_guard_flags_third_party_clock_and_other_quiz_packages() -> None:
    source = "import redis, time\nfrom quiz.adapters import x\nfrom fractions import Fraction\n"
    flagged = {m for m in _imported_modules(source, "quiz.domain") if not _allowed(m)}
    assert flagged == {"redis", "time", "quiz.adapters"}
    required = {"uuid", "secrets", "pathlib", "subprocess", "sys", "shutil", "tempfile", "signal"}
    required |= {"select", "selectors", "multiprocessing", "concurrent", "http", "urllib", "ssl"}
    required |= {"sqlite3", "logging", "importlib", "concurrent.futures", "http.client"}
    source = "".join(f"import {module}\n" for module in sorted(required))
    assert {m for m in _imported_modules(source, "quiz.domain") if _allowed(m)} == set()


def test_guard_resolves_relative_imports() -> None:
    source = (
        "from .scoring import points\nfrom . import standings\n"
        "from ..adapters import redis_store\nfrom .. import app\n"
    )
    flagged = {m for m in _imported_modules(source, "quiz.domain") if not _allowed(m)}
    assert flagged == {"quiz.adapters", "quiz.app"}
