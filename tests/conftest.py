"""Shared fixtures: isolated ZYKO dirs + scripted fake providers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the repo src layout is importable even without an editable install.
ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
sys.path.insert(0, SRC)
# Subprocess tests (`python -m zyko …`, MCP server round-trips, integration
# flows) spawn `sys.executable` fresh — a sys.path tweak in THIS process does
# not reach them, so on a clean checkout without `pip install -e .` they used
# to die with "No module named zyko" (7 failures in one CI-less run).
# Exporting PYTHONPATH here makes every child inherit the same source tree.
_os_path = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
if SRC not in _os_path:
    os.environ["PYTHONPATH"] = os.pathsep.join([SRC, *_os_path])


@pytest.fixture(autouse=True)
def isolated_zyko_dirs(tmp_path, monkeypatch):
    """Every test runs against throwaway config/data/cache directories."""
    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ZYKO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZYKO_CACHE_DIR", str(tmp_path / "cache"))
    yield tmp_path
