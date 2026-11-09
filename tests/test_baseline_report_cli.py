"""اختبارات مخرجات zyko.baseline: JSON حتمي + نص عربي + تقرير HTML RTL + CLI.

العقد المُختبر هنا:
- JSON يُحمَّل ويبقى متطابق البايتات بين تشغيلين على نفس الحالة
- التقرير النصي عربي مقروء ويعرض الحكم والحالات بالعربية
- تقرير HTML حتمي البايتات، RTL، بلا جافاسكربت، وكل القيم مهرَّبة
- CLI: أكواد الخروج 0/1/2 معروفة، و--html يكتب فقط عند الطلب
"""

from __future__ import annotations

import json

import pytest

from zyko.baseline.__main__ import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main
from zyko.baseline.engine import BaselineEngine
from zyko.baseline.report import (
    baseline_check_summary_line,
    baseline_check_to_html,
    baseline_check_to_json,
    baseline_check_to_text,
    baseline_promise_text,
    baseline_update_summary_line,
    baseline_update_to_json,
    baseline_update_to_text,
)

BUGGY = """import os


def flip(flag):
    return flag == None


def guarded(block):
    try:
        block()
    except:
        raise ValueError("فشل")
"""

CLEAN = '''"""نظيف."""


def add(a: int, b: int) -> int:
    """يجمع."""
    return a + b
'''


@pytest.fixture()
def project(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "mod.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (src / "clean.py").write_text(CLEAN, encoding="utf-8", newline="\n")
    return src


@pytest.fixture()
def guarded_project(project):
    """مشروع له خط أساس مسجّل."""
    assert BaselineEngine().update(project).ok
    return project


# -------------------------------------------------------------- JSON
def test_update_json_loadable_and_deterministic(project, tmp_path):
    src2 = tmp_path / "proj2"
    src2.mkdir()
    (src2 / "mod.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (src2 / "clean.py").write_text(CLEAN, encoding="utf-8", newline="\n")
    r1 = BaselineEngine().update(project)
    r2 = BaselineEngine().update(src2)
    j1, j2 = baseline_update_to_json(r1), baseline_update_to_json(r2)
    d1 = json.loads(j1)
    assert d1["schema"] == "zyko.baseline/1" and d1["mode"] == "update"
    d1.pop("src"), d1.pop("baseline_path")
    d2 = json.loads(j2)
    d2.pop("src"), d2.pop("baseline_path")
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


def test_check_json_loadable_and_deterministic(guarded_project, tmp_path):
    src2 = tmp_path / "proj2"
    src2.mkdir()
    (src2 / "mod.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (src2 / "clean.py").write_text(CLEAN, encoding="utf-8", newline="\n")
    BaselineEngine().update(src2)
    r1 = BaselineEngine().check(guarded_project)
    r2 = BaselineEngine().check(src2)
    d1 = json.loads(baseline_check_to_json(r1))
    d2 = json.loads(baseline_check_to_json(r2))
    for d in (d1, d2):
        d.pop("src"), d.pop("baseline_path")
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


# --------------------------------------------------------------- نص
def test_update_text_is_arabic_and_complete(project):
    r = BaselineEngine().update(project)
    t = baseline_update_to_text(r)
    assert "حارس الجودة" in t and project.name in t
    assert "أدنى درجة" in t and "ملاحظات مسجَّلة" in t
    assert "لا يُكتب على القرص شيء" in t
    s = baseline_update_summary_line(r)
    assert "أُنشئ خط الأساس" in s and str(r.run_no) in s


def test_update_text_failure_is_arabic():
    from zyko.baseline.engine import BaselineUpdateResult

    r = BaselineUpdateResult(
        src="x", baseline_path="", ok=False, failed_stage="scan", error_ar="المجلد غير موجود: x"
    )
    t = baseline_update_to_text(r)
    assert "فشل التحديث" in t and "المجلد غير موجود" in t
    assert "المسح" in baseline_update_summary_line(r)


def test_check_text_shows_statuses_and_history(guarded_project):
    (guarded_project / "mod.py").write_text(
        BUGGY + "\n\n\ndef probe(x):\n    return eval(x)\n", encoding="utf-8"
    )
    r = BaselineEngine().check(guarded_project)
    t = baseline_check_to_text(r)
    assert "تراجع" in t and "mod.py" in t
    assert "الحكم:" in t and "قراءة فقط" in t
    s = baseline_check_summary_line(r)
    assert "تراجع" in s and "ملاحظات جديدة" in s


def test_check_text_missing_baseline(guarded_project):
    (guarded_project / ".zyko" / "baseline.json").unlink()
    r = BaselineEngine().check(guarded_project)
    t = baseline_check_to_text(r)
    assert "لا خط أساس" in t and "update" in t


def test_promise_text_lists_guarantees():
    t = baseline_promise_text()
    assert "zyko.baseline/1" in t
    assert "update" in t and "check" in t
    assert "حتمي البايتات" in t or "حتمية" in t


# --------------------------------------------------------------- HTML
def test_html_is_deterministic_rtl_and_scriptless(guarded_project):
    r = BaselineEngine().check(guarded_project)
    h1 = baseline_check_to_html(r)
    h2 = baseline_check_to_html(BaselineEngine().check(guarded_project))
    assert h1 == h2  # حتمي البايتات
    assert 'dir="rtl"' in h1 and 'lang="ar"' in h1
    assert "<script" not in h1 and "javascript:" not in h1
    assert "حارس الجودة" in h1
    assert "mod.py" in h1 and "clean.py" in h1
    assert "<!DOCTYPE html>" in h1


def test_html_regresion_is_marked(guarded_project):
    (guarded_project / "mod.py").write_text(
        BUGGY + "\n\n\ndef probe(x):\n    return eval(x)\n", encoding="utf-8"
    )
    r = BaselineEngine().check(guarded_project)
    h = baseline_check_to_html(r)
    assert "st-regressed" in h and "تراجع مكتشف" in h


def test_html_escapes_hostile_paths():
    """مسار يحمل رموز HTML يجب أن يُهرَّب لا يُنفَّذ.

    المسار العدائي يُبنى في النتيجة مباشرة (بلا ملف حقيقي) — فأسماء
    الملفات ذات ``< >`` غير قانونية على Windows، وهروب HTML عقد في
    الدالة نفسها لا في نظام الملفات.
    """
    from zyko.baseline.engine import BaselineCheckResult

    r = BaselineCheckResult(
        src="proj",
        baseline_path="b.json",
        reviewed=1,
        per_file=[
            {
                "path": "<script>alert(1)</script>.py",
                "status": "regressed",
                "score_baseline": 100,
                "score_current": 83,
                "new_findings": 2,
                "resolved_findings": 0,
                "sha_changed": True,
            }
        ],
    )
    h = baseline_check_to_html(r)
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;" in h
    assert "st-regressed" in h


def test_html_failure_and_missing_states():
    from zyko.baseline.engine import BaselineCheckResult

    bad = BaselineCheckResult(
        src="x", baseline_path="", ok=False, failed_stage="baseline", error_ar="فاسد"
    )
    h = baseline_check_to_html(bad)
    assert "فشل" in h and "فاسد" in h
    missing = BaselineCheckResult(src="y", baseline_path="", baseline_status="missing")
    h2 = baseline_check_to_html(missing)
    assert "لا خط أساس" in h2 and "update" in h2


# ---------------------------------------------------------------- CLI
def test_cli_update_check_show_roundtrip(project, capsys):
    assert main(["update", "--src", str(project)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "خط الأساس" in out
    assert main(["check", "--src", str(project)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "الجودة ثابتة" in out
    assert main(["show", "--src", str(project)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "سجل التشغيلات" in out and "mod.py" in out


def test_cli_check_detects_regression_exit_1(guarded_project):
    (guarded_project / "mod.py").write_text(
        BUGGY + "\n\n\ndef probe(x):\n    return eval(x)\n", encoding="utf-8"
    )
    assert main(["check", "--src", str(guarded_project)]) == EXIT_FINDINGS


def test_cli_check_missing_baseline_exit_1(tmp_path):
    src = tmp_path / "fresh"
    src.mkdir()
    (src / "a.py").write_text(CLEAN, encoding="utf-8")
    assert main(["check", "--src", str(src)]) == EXIT_FINDINGS
    assert main(["show", "--src", str(src)]) == EXIT_FINDINGS


def test_cli_update_structured_failure_exit_2(tmp_path):
    assert main(["update", "--src", str(tmp_path / "لا-يوجد")]) == EXIT_USAGE


def test_cli_json_and_summary_formats(guarded_project, capsys):
    assert main(["check", "--src", str(guarded_project), "--format", "json"]) == EXIT_OK
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == "zyko.baseline/1" and d["mode"] == "check"
    assert main(["update", "--src", str(guarded_project), "--format", "summary"]) == EXIT_OK
    assert "حُدِّث خط الأساس" in capsys.readouterr().out


def test_cli_html_flag_writes_deterministic_file(guarded_project, tmp_path, capsys):
    out_file = tmp_path / "reports" / "guard.html"
    assert main(["check", "--src", str(guarded_project), "--html", str(out_file)]) == EXIT_OK
    assert out_file.is_file()
    first = out_file.read_bytes()
    assert main(["check", "--src", str(guarded_project), "--html", str(out_file)]) == EXIT_OK
    assert out_file.read_bytes() == first  # حتمي البايتات
    assert 'dir="rtl"' in first.decode("utf-8")


def test_cli_html_to_directory_is_usage_error(guarded_project, tmp_path):
    d = tmp_path / "html-dir"
    d.mkdir()
    assert main(["check", "--src", str(guarded_project), "--html", str(d)]) == EXIT_USAGE


def test_cli_check_structured_failure_exit_2(project):
    bad = project.parent / "bad.json"
    bad.write_text("{فاسد", encoding="utf-8")
    assert main(["check", "--src", str(project), "--baseline", str(bad)]) == EXIT_USAGE


def test_cli_gate_and_promise(capsys):
    assert main(["promise"]) == EXIT_OK
    assert "zyko.baseline/1" in capsys.readouterr().out
    assert main(["gate"]) == EXIT_OK
    assert "بوابة المرحلة 6" in capsys.readouterr().out
