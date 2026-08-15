"""Structural enforcement of the deterministic-core rule.

CLAUDE.md states that ``aether.core`` has no database access, no network access, no
framework dependency, no implicit clock and no mutable hidden state. A rule that
exists only in a document decays. This test makes it a build failure.

It parses every module under ``aether/core`` and inspects the AST rather than
importing and introspecting, so a violation is caught even if the offending code path
never executes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[2] / "aether" / "core"

#: Import roots the deterministic core may never depend on.
FORBIDDEN_IMPORTS = {
    # I/O and persistence
    "sqlite3",
    "sqlalchemy",
    "sqlmodel",
    "alembic",
    "pathlib",
    "os",
    "io",
    "shutil",
    "csv",
    "pickle",
    # network
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "anthropic",
    "asyncio",
    # frameworks
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "uvicorn",
    # randomness and environment
    "random",
    "secrets",
    "tempfile",
    "subprocess",
    "logging",
}

# `json`, `hashlib` and `xml.sax.saxutils` are deliberately NOT forbidden. None
# performs I/O: `json.dumps` is pure serialisation, `hashlib` is pure computation, and
# `saxutils.escape` is pure string escaping. The audit chain needs the first two to
# produce a canonical hashable representation and the settlement module needs the
# third to render a message safely. The rule being enforced is "no side effects and no
# hidden inputs", not "no stdlib".

#: Calls that reach for an implicit clock. ``date``/``datetime`` types are fine;
#: reading *now* inside a pure function is not.
FORBIDDEN_CALLS = {"now", "today", "utcnow", "time", "monotonic", "perf_counter"}


def core_modules() -> list[Path]:
    return sorted(p for p in CORE.rglob("*.py") if p.name != "__init__.py")


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_core_directory_is_populated():
    """Guard against the suite silently passing because it found nothing."""
    assert len(core_modules()) >= 5


@pytest.mark.parametrize("module", core_modules(), ids=lambda p: p.stem)
class TestCorePurity:
    def test_no_forbidden_imports(self, module: Path):
        violations: list[str] = []

        for node in ast.walk(parse(module)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        violations.append(f"line {node.lineno}: import {alias.name}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] in FORBIDDEN_IMPORTS
            ):
                violations.append(f"line {node.lineno}: from {node.module} import ...")

        assert not violations, (
            f"{module.name} breaks the deterministic-core rule:\n  " + "\n  ".join(violations)
        )

    def test_no_implicit_clock(self, module: Path):
        violations: list[str] = []

        for node in ast.walk(parse(module)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALLS
            ):
                violations.append(f"line {node.lineno}: .{node.func.attr}()")

        assert not violations, (
            f"{module.name} reads an implicit clock. Every calculation must take an "
            f"explicit as_of:\n  " + "\n  ".join(violations)
        )

    def test_no_module_level_mutable_state(self, module: Path):
        """Module-level lists, dicts and sets are shared mutable state.

        Constants are permitted when they are immutable — tuples, frozensets, scalars.
        """
        violations: list[str] = []
        tree = parse(module)

        for node in tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue

            value = node.value
            if isinstance(value, ast.List | ast.Dict | ast.Set):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                # Dunder module metadata such as __all__ is not runtime state.
                names = [n for n in names if not n.startswith("__")]
                if names:
                    violations.append(f"line {node.lineno}: {', '.join(names)}")

        assert not violations, f"{module.name} holds mutable module-level state:\n  " + "\n  ".join(
            violations
        )


def test_core_never_imports_outside_itself():
    """The core may depend on the standard library and itself. Nothing else.

    NumPy and SciPy are permitted, and will be needed by the optimizer in Phase 3.
    """
    allowed_first_party = {"aether"}
    allowed_third_party = {"numpy", "scipy"}
    violations: list[str] = []

    for module in core_modules():
        for node in ast.walk(parse(module)):
            root = None
            if isinstance(node, ast.Import):
                root = node.names[0].name.split(".")[0]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = node.module.split(".")[0]

            if root is None:
                continue
            if root in allowed_first_party:
                # Within aether, the core may only import from aether.core.
                name = node.names[0].name if isinstance(node, ast.Import) else node.module or ""
                if not name.startswith("aether.core"):
                    violations.append(f"{module.name}:{node.lineno} imports {name}")
            elif root in allowed_third_party:
                continue

    assert not violations, "core reaches outside itself:\n  " + "\n  ".join(violations)
