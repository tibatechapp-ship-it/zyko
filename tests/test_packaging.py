"""Packaging invariants: pyproject.toml must keep every promise the README makes.

The flagship test here caught a real bug: the `structured` extra shipped
`pydantic>=2.0` ungated, so `pip install zyko[structured]` broke on
Python 3.14 / Termux — the exact platform ZYKO advertises first-class —
while the `dev` extra was already gated.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import zyko

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _data() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _all_requirements(data: dict) -> list[tuple[str, str]]:
    """(where, requirement-string) for the base deps and every extra."""
    out: list[tuple[str, str]] = []
    for req in data["project"].get("dependencies", []):
        out.append(("dependencies", req))
    for extra, reqs in data["project"].get("optional-dependencies", {}).items():
        for req in reqs:
            out.append((f"extra:{extra}", req))
    return out


def test_pydantic_is_gated_behind_python_3_14():
    """Every pydantic requirement anywhere in pyproject.toml must carry the
    marker `python_version < '3.14'` — pydantic-core has no wheel for
    Python 3.14 on Termux/Android, so an ungated pin breaks the install
    on the platform ZYKO advertises first-class."""
    for where, req in _all_requirements(_data()):
        if "pydantic" in req.lower():
            assert "python_version < '3.14'" in req, (
                f"pydantic must be gated with python_version < '3.14', got: {req!r} (in {where})"
            )


def test_base_dependencies_are_exactly_httpx_and_pyyaml():
    deps = _data()["project"]["dependencies"]
    names = {req.split(">")[0].split("=")[0].strip().lower() for req in deps}
    assert names == {"httpx", "pyyaml"}, f"runtime deps drifted: {names}"


def test_core_extras_declared():
    extras = set(_data()["project"]["optional-dependencies"])
    for extra in ("ui", "structured", "dev", "android"):
        assert extra in extras, f"advertised extra missing: {extra}"


def test_dev_extra_carries_the_test_stack():
    dev = " ".join(_data()["project"]["optional-dependencies"]["dev"])
    for pkg in ("pytest", "pytest-asyncio", "ruff"):
        assert pkg in dev, f"dev extra lost {pkg}"


def test_console_script_points_to_cli():
    scripts = _data()["project"]["scripts"]
    assert scripts.get("zyko") == "zyko.cli:main"


def test_requires_python_floor():
    assert _data()["project"]["requires-python"] == ">=3.11"


def test_classifiers_cover_every_supported_python():
    classifiers = "\n".join(_data()["project"]["classifiers"])
    for minor in ("3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {minor}" in classifiers


def test_project_urls_complete():
    urls = _data()["project"]["urls"]
    for key in ("Homepage", "Repository", "Documentation", "Issues"):
        assert key in urls, f"project URL missing: {key}"
        assert urls[key].startswith("https://"), f"{key} must be https"


def test_readme_declared_and_present():
    project = _data()["project"]
    assert project["readme"] == "README.md"
    readme = ROOT / "README.md"
    assert readme.is_file() and readme.stat().st_size > 5_000


def test_declared_version_matches_runtime_and_readme():
    declared = _data()["project"]["version"]
    assert declared == zyko.__version__, (
        f"pyproject says {declared!r}, zyko.version says {zyko.__version__!r}"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert declared in readme, f"README does not advertise the released version {declared}"
