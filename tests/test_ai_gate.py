"""اختبارات بوابة المرحلة 8: طبقة الذكاء خضعت للمصنع أم لا؟ 12 بوابة."""

from __future__ import annotations

import time

import pytest

from zyko.ai.gate import run_phase8_gate


@pytest.fixture(scope="module")
def gate_result() -> object:
    return run_phase8_gate(max_seconds=30.0)


def test_gate_all_twelve_pass(gate_result: object) -> None:
    assert gate_result.ok, gate_result.table_ar()  # type: ignore[attr-defined]
    assert len(gate_result.rows) == 12  # type: ignore[attr-defined]


def test_gate_anchors_covered(gate_result: object) -> None:
    anchors = {r.anchor for r in gate_result.rows}  # type: ignore[attr-defined]
    assert anchors == {"نظيف", "مريب", "عدائي"}


def test_gate_table_is_arabic_and_signed(gate_result: object) -> None:
    table = gate_result.table_ar()  # type: ignore[attr-defined]
    assert "بوابة المرحلة 8" in table
    assert "طبقة الذكاء مقبولة ✅" in table
    assert "12/12" in table


def test_gate_runs_within_budget(gate_result: object) -> None:
    assert gate_result.seconds < 30.0  # type: ignore[attr-defined]


def test_gate_is_repeatable() -> None:
    started = time.perf_counter()
    first = run_phase8_gate(max_seconds=30.0)
    second = run_phase8_gate(max_seconds=30.0)
    assert first.ok and second.ok
    assert first.table_ar() == second.table_ar()  # حتمية الحكم نصًا
    assert time.perf_counter() - started < 60.0
