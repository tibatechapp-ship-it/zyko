"""اختبارات ربط لوحة التحكم ببوابة المصنع: gates --html/--md وأمر dashboard."""

from __future__ import annotations

import pytest

from zyko.factory.cli import main as factory_main


def test_gates_writes_html_and_md(tmp_path):
    h1, m1 = tmp_path / "gates.html", tmp_path / "gates.md"
    h2, m2 = tmp_path / "gates2.html", tmp_path / "gates2.md"
    code = factory_main(["gates", "--html", str(h1), "--md", str(m1)])
    assert code in (0, 1)
    html1 = h1.read_text(encoding="utf-8")
    md1 = m1.read_text(encoding="utf-8")
    assert 'dir="rtl"' in html1
    assert "البوابات" in html1
    assert "لوحة تحكم" in md1
    factory_main(["gates", "--html", str(h2), "--md", str(m2)])
    assert h1.read_bytes() == h2.read_bytes()
    assert m1.read_bytes() == m2.read_bytes()


def test_dashboard_command_writes_both(tmp_path):
    h, m = tmp_path / "d.html", tmp_path / "d.md"
    code = factory_main(["dashboard", "--html", str(h), "--md", str(m)])
    assert code in (0, 1)
    out = h.read_text(encoding="utf-8")
    for phase in ("المرحلة 3", "المرحلة 4", "المرحلة 5", "المرحلة 6"):
        assert phase in out
    assert "البصمة:" in out
    assert m.exists()


def test_dashboard_requires_output_target(capsys: pytest.CaptureFixture[str]):
    code = factory_main(["dashboard"])
    assert code == 2
    out = capsys.readouterr().out
    assert "--html" in out
