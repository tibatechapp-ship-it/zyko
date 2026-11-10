"""Architectural invariants: clean imports, strict layering, zero-dependency core.

These tests hold the architecture in place while features land. If an import
cycle appears, a lower layer starts reaching upwards, or an optional heavy
dependency sneaks into the entrypoint import chain, one of these fails —
before a user on Termux (where pydantic-core has no wheel) ever sees it.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import zyko

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ZYKO = SRC / "zyko"

# Optional extras (ui/structured/android). A module may fail to import ONLY
# because one of these is absent; any other ImportError is architecture rot.
OPTIONAL_ROOTS = {"rich", "pydantic", "pydantic_core", "kivy"}

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# Upper layers that the zero-dependency core must never reach up into.
UPPER_LAYERS = {
    "agents",
    "ai",
    "client",
    "cli",
    "coder",
    "crew",
    "dashboard",
    "factory",
    "fixer",
    "gateway",
    "mcp",
    "pipeline",
    "reviewer",
    "router",
    "workspace",
}


def _optional_root_of(exc: BaseException) -> str | None:
    """Missing optional root module if *exc* (or its chain) is caused by one."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ImportError):
            name = getattr(exc, "name", "") or ""
            root = name.split(".")[0]
            if root in OPTIONAL_ROOTS:
                return root
            for opt in OPTIONAL_ROOTS:
                if f"'{opt}'" in str(exc) or f'"{opt}"' in str(exc):
                    return opt
        exc = exc.__cause__ or exc.__context__
    return None


def _import_roots(path: Path) -> list[str]:
    """Top-level absolute import names of one Python file (AST scan)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def _zyko_module_targets(imported: str) -> list[str]:
    """`zyko.X.Y` → ['X']; absolute names outside the package are ignored."""
    parts = imported.split(".")
    if parts[0] != "zyko" or len(parts) < 2:
        return []
    return [parts[1]]


def test_zyko_imports_cleanly_and_reports_semver():
    import importlib

    mod = importlib.import_module("zyko")
    assert SEMVER.match(mod.__version__), f"not semver: {mod.__version__!r}"
    assert mod.PROTOCOL_VERSION


def test_every_submodule_imports_cleanly():
    import importlib
    import pkgutil

    failures: list[tuple[str, str]] = []
    walked: list[str] = []
    for info in pkgutil.walk_packages(zyko.__path__, prefix="zyko."):
        walked.append(info.name)
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001 - the point is to classify it
            if _optional_root_of(exc) is not None:
                continue  # pydantic/rich absent (py3.14 local run) — allowed
            failures.append((info.name, f"{type(exc).__name__}: {exc}"))
    assert len(walked) > 50, f"walk found too few modules: {len(walked)}"
    assert not failures, f"modules with real import failures: {failures}"


def test_fresh_interpreter_imports_the_whole_package():
    """Import every module in a virgin interpreter — catches import-order
    side effects and cycles that an already-warm process hides."""
    code = (
        "import importlib, pkgutil, sys, zyko\n"
        "real = []\n"
        "for m in pkgutil.walk_packages(zyko.__path__, prefix='zyko.'):\n"
        "    try:\n"
        "        importlib.import_module(m.name)\n"
        "    except Exception as e:\n"
        "        missing = getattr(e, 'name', '') or str(e)\n"
        "        if any(o in missing for o in ('rich', 'pydantic', 'kivy')):\n"
        "            continue\n"
        "        real.append((m.name, type(e).__name__, str(e)))\n"
        "print(real)\n"
        "sys.exit(1 if real else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0, f"fresh-import failures: {proc.stdout} {proc.stderr}"


def test_entrypoint_imports_without_optional_heavy_deps():
    """The Termux invariant: `import zyko` + the CLI must work with rich and
    pydantic made unimportable — exactly the state of a py3.14 Termux box."""
    code = (
        "import sys\n"
        f"BLOCKED = {sorted(OPTIONAL_ROOTS)!r}\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BLOCKED:\n"
        "            raise ImportError(f'blocked optional dep: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "import zyko, zyko.cli\n"
        "zyko.cli.build_parser()\n"
        "print('entrypoint-ok')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, f"entrypoint broke without optional deps: {proc.stderr}"
    assert "entrypoint-ok" in proc.stdout


def test_core_is_third_party_free():
    """core/ + platform/ + exceptions/version/log import the stdlib and zyko
    only — the zero-dependency core the README promises."""
    targets = [
        ZYKO / "core",
        ZYKO / "platform",
        ZYKO / "exceptions.py",
        ZYKO / "version.py",
        ZYKO / "log.py",
    ]
    offenders: list[tuple[str, str]] = []
    for target in targets:
        files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for path in files:
            for root in _import_roots(path):
                if root not in sys.stdlib_module_names and root != "zyko":
                    offenders.append((str(path.relative_to(ROOT)), root))
    assert not offenders, f"third-party imports in the core: {offenders}"


def test_lower_layers_never_import_upper_layers():
    """core/ and platform/ are the bottom of the stack: no upward edges."""
    offenders: list[tuple[str, str]] = []
    for layer in ("core", "platform"):
        for path in sorted((ZYKO / layer).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    for sub in _zyko_module_targets(name):
                        if sub in UPPER_LAYERS:
                            offenders.append((str(path.relative_to(ROOT)), f"zyko.{sub}"))
    assert not offenders, f"lower layers import upper layers: {offenders}"
