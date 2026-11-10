"""Deterministic Arabic dashboard — HTML + Markdown only, zero JavaScript."""

from __future__ import annotations

from zyko.dashboard.generator import (
    DashboardInput,
    FileScore,
    GateResult,
    build_dashboard,
    build_from_gates,
    build_markdown,
    build_markdown_from_gates,
)

__all__ = [
    "DashboardInput",
    "FileScore",
    "GateResult",
    "build_dashboard",
    "build_from_gates",
    "build_markdown",
    "build_markdown_from_gates",
]
