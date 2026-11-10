"""Repository-health invariants — the checks that keep the project honest.

These guard the meta-layer every other test assumes: CI structure, citation
metadata, release hygiene, harness wiring. Each exists because something
actually drifted:
- CITATION.cff said 0.13.0 while the package was five releases ahead;
- pytest-asyncio's deprecation warning polluted every run (CI, Termux, local)
  because the loop scope was never pinned;
- subprocess tests silently required `pip install -e .` — on a clean checkout
  7 of them died with "No module named zyko" while CI stayed green.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CI = ROOT / ".github" / "workflows" / "ci.yml"

MANDATORY_JOBS = {"test", "lint", "security", "rust-kernel", "cli-smoke"}


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _ci() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_citation_cff_tracks_the_released_version():
    """CITATION.cff froze at 0.13.0 for five releases — anyone citing ZYKO
    got a stale version. It must always equal pyproject's version."""
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    declared = _pyproject()["project"]["version"]
    match = re.search(r'^version:\s*"?([^"\n]+)"?', cff, re.MULTILINE)
    assert match, "CITATION.cff has no version field"
    assert match.group(1).strip() == declared, (
        f"CITATION.cff says {match.group(1)!r}, package is {declared!r}"
    )


def test_citation_cff_license_and_repository_point_at_the_project():
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "Apache-2.0" in cff
    repo = _pyproject()["project"]["urls"]["Repository"]
    assert repo in cff, f"CITATION.cff repository-code must contain {repo}"


def test_ci_matrix_covers_three_os_and_three_pythons():
    matrix = _ci()["jobs"]["test"]["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert set(str(p) for p in matrix["python"]) == {"3.11", "3.12", "3.13"}


def test_ci_keeps_its_mandatory_jobs_and_phase_gates():
    jobs = set(_ci()["jobs"])
    missing = MANDATORY_JOBS - jobs
    assert not missing, f"CI lost mandatory jobs: {missing}"
    phases = {j for j in jobs if re.match(r"phase-?0", j)}
    phase_keys = {j for j in jobs if j.startswith("phase")}
    assert len(phase_keys) >= 9, f"the nine phase gates shrank to {sorted(phase_keys)}"
    assert phases, "phase-0 tools gate missing"


def test_lint_job_enforces_format_not_only_imports():
    raw = CI.read_text(encoding="utf-8")
    lint = raw.split("  lint:", 1)[1].split("\n  security:", 1)[0]
    assert "ruff check" in lint
    assert "ruff format --check" in lint, (
        "the lint job must keep enforcing ruff format, not just imports"
    )


def test_pytest_config_pins_asyncio_loop_scope_and_fails_on_deprecations():
    cfg = _pyproject()["tool"]["pytest"]["ini_options"]
    assert cfg.get("asyncio_default_fixture_loop_scope") == "function", (
        "unpinned loop scope = PytestDeprecationWarning on every run again"
    )
    filters = [str(f) for f in cfg.get("filterwarnings", [])]
    assert any("error::pytest.PytestDeprecationWarning" in f for f in filters), (
        "deprecation warnings from pytest must keep failing the suite"
    )


def test_conftest_exports_pythonpath_to_subprocesses():
    """Subprocess tests spawn `sys.executable` fresh; without this export a
    clean checkout (no editable install) cannot import zyko in children.
    The child here inherits the environment pytest's conftest prepared."""
    code = "import os, sys; print(os.environ.get('PYTHONPATH', ''))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert str(SRC) in out.stdout.splitlines()[0], (
        "conftest must export PYTHONPATH=src so subprocess tests survive "
        "without an editable install"
    )


def test_changelog_documents_the_released_version():
    version = _pyproject()["project"]["version"]
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Convention: '## 0.19.0 — title …' — the version leads the heading.
    headings = re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    lead = [h.split()[0] for h in headings if h.split()]
    assert version in lead, f"CHANGELOG has no '## {version}' section (found: {headings[:5]}…)"


def test_no_merge_conflict_markers_in_source():
    offenders: list[str] = []
    for base in (SRC, ROOT / "tests"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith(("<<<<<<< ", ">>>>>>> ")):
                    offenders.append(str(path.relative_to(ROOT)))
                elif line.rstrip() == "=======" and path.suffix == ".py":
                    offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"merge markers left in: {sorted(set(offenders))}"


def test_test_suite_collection_is_intact():
    """A broken import or syntax error inside any test file silently drops
    tests from the run — CI would stay green while coverage evaporates."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    assert proc.returncode == 0, f"collection broke: {proc.stderr[-500:]}"
    # -q format: one 'tests/test_x.py: N' line per file — the total is their sum.
    counts = [
        int(m.group(1))
        for line in proc.stdout.splitlines()
        if (m := re.match(r"^tests/[^:\s]+\.py:\s*(\d+)$", line.strip()))
    ]
    assert counts, f"cannot parse per-file counts: {proc.stdout[-300:]}"
    total = sum(counts)
    assert total >= 1600, (
        f"only {total} tests collected across {len(counts)} files "
        "(expected ≥1600) — something silently dropped"
    )
