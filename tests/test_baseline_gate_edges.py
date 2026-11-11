"""تغطية أطر بوابة خط الأساس (`baseline/gate.py`) — الفروع الموثقة التي
كشفها قياس التغطية: الملف الضحية، المراسي بلا بايثون، فشل التحديث،
ومسار العرض الفاشل.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from zyko.baseline.engine import BaselineEngine
from zyko.baseline.gate import _build_tree, _run_anchor, _victim_file, run_phase6_gate

GOOD_PY = 'def add(a, b):\n    """جمع عددين."""\n    return a + b\n\n\ndef sub(a, b):\n    """طرح عددين."""\n    return a - b\n'


def _daad_available() -> bool:
    try:
        return (
            subprocess.run(  # nosec B607
                [sys.executable, "-m", "daad", "version"], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


def test_victim_file_picks_first_python_text_file():
    files = {"b.bin": b"\x00\x01", "a.py": GOOD_PY, "c.py": GOOD_PY}
    assert _victim_file(files) == "a.py"


def test_victim_file_none_without_python_text():
    files = {"a.bin": b"\x00", "b.dat": b"\x01"}
    assert _victim_file(files) is None


def test_build_tree_writes_bytes_as_bytes(tmp_path):
    files = {"data.bin": b"\x00\x01\x02", "app.py": GOOD_PY}
    root = tmp_path / "tree"
    _build_tree(root, files)
    assert (root / "data.bin").read_bytes() == b"\x00\x01\x02"
    assert (root / "app.py").read_text(encoding="utf-8") == GOOD_PY


def test_run_anchor_binary_only_documents_zero_reviewed(tmp_path):
    """مرساة بلا بايثون نصي — التحديث ينجح لكن المراقبة صفر: حالة موثقة."""
    engine = BaselineEngine()
    files = {"data.bin": b"\x00\x01", "readme.md": "# نص"}
    row = _run_anchor(engine, "بلا بايثون", files, tmp_path)
    assert not row.completed
    assert any("لم تُراقَب أي ملفات" in p for p in row.problems)


def test_run_anchor_full_cycle_detects_regression_and_improvement(tmp_path):
    """المرساة الكاملة: تحديث → فحص → إفساد يُكشف → تحسّن يُعلن."""
    engine = BaselineEngine()
    files = {"app.py": GOOD_PY, "utils.py": 'def div(a, b):\n    """قسمة."""\n    return a / b\n'}
    row = _run_anchor(engine, "دورة كاملة", files, tmp_path)
    assert row.completed, row.problems
    assert row.detects_regression, row.problems
    assert row.detects_improvement, row.problems
    assert row.problems == []
    assert row.seconds >= 0.0


def test_run_anchor_update_failure_is_documented(tmp_path, monkeypatch):
    """فشل التحديث يُسجَّل في الصف ولا يرفع استثناء."""
    engine = BaselineEngine()

    def broken_update(_src):
        return types_simple_namespace()

    def types_simple_namespace():
        import types

        return types.SimpleNamespace(
            ok=False, failed_stage="scan", error_ar="خطأ محقون", reviewed=0
        )

    monkeypatch.setattr(engine, "update", broken_update)
    row = _run_anchor(engine, "فشل التحديث", {"app.py": GOOD_PY}, tmp_path)
    assert not row.completed
    assert any("فشل التحديث في scan" in p for p in row.problems)


def test_phase6_gate_with_custom_anchor_deterministic(tmp_path):
    """البوابة الكاملة بمرساة مخصصة — الحكم حتمي بين تشغيلين."""
    anchors = (("اختبار", {"app.py": GOOD_PY}),)
    r1 = run_phase6_gate(anchors=anchors, tmp_root=tmp_path)
    r2 = run_phase6_gate(anchors=anchors, tmp_root=tmp_path)
    assert r1.ok and r2.ok

    # الحكم حتمي؛ الزمن المقاس وحده يختلف بين التشغيلين — فمقارنة البنية:
    def structure(result):
        return [
            (
                row.name,
                row.completed,
                row.detects_regression,
                row.detects_improvement,
                tuple(row.problems),
            )
            for row in result.rows
        ]

    assert structure(r1) == structure(r2)
    text = r1.table_ar()
    assert "النتيجة: البوابة ناجحة" in text
    assert "↳" not in text  # لا مشاكل في المرساة السليمة


@pytest.mark.skipif(not _daad_available(), reason="daad not installed")
def test_phase6_gate_text_renders_victim_problems(tmp_path):
    """صف فاشل يعرض مشاكله بالسهم — نصف الضاد في المرساة يكسر الركن."""
    anchors = (("مُفسِد", {"app.py": "مرحبا("}),)
    result = run_phase6_gate(anchors=anchors, tmp_root=tmp_path)
    text = result.table_ar()
    assert "↳" in text
