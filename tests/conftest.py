"""Shared fixtures: isolated ZYKO dirs + scripted fake providers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the repo src layout is importable even without an editable install.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def isolated_zyko_dirs(tmp_path, monkeypatch):
    """Every test runs against throwaway config/data/cache directories."""
    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ZYKO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZYKO_CACHE_DIR", str(tmp_path / "cache"))
    yield tmp_path
