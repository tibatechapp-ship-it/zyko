"""اختبارات compare — منصة المقارنة الحتمية: صدق أعلى من الفوز.

العقد المُختبر:
1. قياسات zyko حقيقية: دقة 12 مسبارًا، حتمية إيصالين، دوران verify —
   كلها على هدف حقيقي وتعطي ok=True.
2. جانب المنافس غائب ⇒ «لم يُشغَّل» موثقة — لا صفر ولا رقم مستعار.
3. جانب المنافس حاضر ⇒ أمر حقيقي يُشغَّل ويُقاس ويُحصى — والفشل
   (أداة مفقودة، رمز خروج، قالب بلا {path}) موثق عربيًا لا مفبرك.
4. الأزمنة خارج الإيصال الحتمي إلا مع include_timing — والتقريران
   بين تشغيلين متطابقان بالبايت.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from zyko.benchmarks.compare import COMPETITOR_NOT_RUN_AR, PROBES, run_compare, verify_probes


def _target(tmp_path: Path) -> Path:
    p = tmp_path / "app.py"
    p.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
    return p


# ------------------------------------------------------------- جدول المسبارات
def test_probe_table_covers_all_tasks() -> None:
    """الجدول يغطي الأنواع الستة + UNKNOWN — لا فئة بلا مسبار."""
    kinds = {expected for _, expected in PROBES}
    assert kinds == {"REVIEW", "FIX", "GENERATE", "TRANSPILE", "VERIFY", "ANALYZE", "UNKNOWN"}
    assert len(PROBES) >= 12 and len({g for g, _ in PROBES}) == len(PROBES)


def test_verify_probes_full_accuracy() -> None:
    """التصنيف الحتمي يجتاز الجدول كاملاً — 12/12 على هذا الإصدار."""
    passed, total, failed = verify_probes()
    assert total == len(PROBES)
    assert passed == total, failed


# ------------------------------------------------------------- القياس الكامل
def test_run_compare_ok_without_competitor(tmp_path: Path) -> None:
    """قياسات zyko كاملة على هدف حقيقي — المنافس غائب موثقًا والتقرير أخضر."""
    report = run_compare(_target(tmp_path), runs=2)
    assert report.ok
    assert report.accuracy == 1.0
    assert report.determinism_ok and report.verify_ok
    assert report.review_median_ms > 0
    assert not report.competitor.ran
    assert report.competitor.error_ar == COMPETITOR_NOT_RUN_AR
    assert report.problems == ()


def test_run_compare_deterministic_receipt_between_calls(tmp_path: Path) -> None:
    """تقريران بنفس المدخل متطابقان بالبايت (بلا أزمنة)."""
    a = run_compare(_target(tmp_path), runs=2).to_json()
    b = run_compare(_target(tmp_path), runs=2).to_json()
    assert a == b


def test_timing_outside_deterministic_receipt(tmp_path: Path) -> None:
    """الأزمنة خارج الإيصال إلا مع include_timing — عقد R2."""
    report = run_compare(_target(tmp_path), runs=2)
    assert "review_median_ms" not in report.to_dict()
    assert "review_median_ms" in report.to_dict(include_timing=True)


def test_runs_below_two_rejected() -> None:
    with pytest.raises(ValueError):
        run_compare("any.py", runs=1)


# ------------------------------------------------------------- جانب المنافس
def test_competitor_runs_real_command(tmp_path: Path) -> None:
    """أمر منافس حقيقي (بايثون مضمّن) يُشغَّل ويُقاس ويُحصى خرجه."""
    target = _target(tmp_path)
    fake_linter = f"{sys.executable} -c \"print('E1'); print('E2')\""
    report = run_compare(target, competitor_cmd=f"{fake_linter} {{path}}", runs=2)
    comp = report.competitor
    assert comp.ran
    assert comp.output_lines == 2
    assert comp.median_ms is not None and comp.median_ms > 0
    assert str(target) in comp.command


def test_competitor_missing_binary_documented(tmp_path: Path) -> None:
    """أداة غير موجودة ⇒ فشل موثق عربيًا (رمز 127 عبر الصدفة) — لا رقم ولا انهيار."""
    report = run_compare(_target(tmp_path), competitor_cmd="zyko-no-such-tool {path}", runs=2)
    assert not report.competitor.ran
    error = report.competitor.error_ar or ""
    assert ("رمز 127" in error) or ("فشل تشغيل المنافس" in error)
    assert "لا رقم مفبرك" in error


def test_competitor_nonzero_exit_documented(tmp_path: Path) -> None:
    """رمز خروج غير صفر ⇒ موثق صادقًا (أداة رفضت الهدف) — لا رقم مفبرك."""
    cmd = f'{sys.executable} -c "import sys; sys.exit(3)"'
    report = run_compare(_target(tmp_path), competitor_cmd=f"{cmd} {{path}}", runs=2)
    assert not report.competitor.ran
    assert "رمز 3" in (report.competitor.error_ar or "")


def test_competitor_template_without_path_rejected(tmp_path: Path) -> None:
    """قالب بلا {path} ⇒ رفض استخدام موثق — لا تخمين لموضع الهدف."""
    report = run_compare(_target(tmp_path), competitor_cmd="ls", runs=2)
    assert not report.competitor.ran
    assert "{path}" in (report.competitor.error_ar or "")


# ------------------------------------------------------------- الجدول وCLI
def test_table_ar_shows_honest_competition(tmp_path: Path) -> None:
    table = run_compare(_target(tmp_path), runs=2).table_ar()
    assert "دقة التصنيف" in table and "12/12" in table
    assert "الحتمية البايتية" in table and "✅" in table
    assert "لم يُشغَّل" in table  # الصدق: المنافس الغائب موثق لا مختلق
    assert "zyko أخضر كامل" in table


def test_cli_compare(tmp_path: Path, capsys) -> None:
    """CLI كامل: zyko compare على ملف حقيقي ⇒ جدول + إيصال JSON مكتوب."""
    from types import SimpleNamespace

    from zyko.cli.commands import cmd_compare

    json_path = tmp_path / "compare.json"
    args = SimpleNamespace(
        target=str(_target(tmp_path)),
        competitor_cmd=None,
        runs=2,
        json_out=str(json_path),
        include_timing=False,
    )
    code = cmd_compare(args)
    out = capsys.readouterr().out
    assert code == 0
    assert "منصة المقارنة الحتمية" in out
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "compare" and payload["ok"] is True
    assert "review_median_ms" not in payload  # الأزمنة خارج الإيصال الحتمي


def test_cli_compare_rejects_single_run(capsys) -> None:
    from types import SimpleNamespace

    from zyko.cli.commands import cmd_compare

    args = SimpleNamespace(
        target="x.py", competitor_cmd=None, runs=1, json_out=None, include_timing=False
    )
    assert cmd_compare(args) == 2
    assert "تشغيلين" in capsys.readouterr().err
