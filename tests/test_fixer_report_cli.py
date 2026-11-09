"""اختبارات التقارير وواجهة الأوامر: حتمية بايتية وعقود أكواد خروج."""

from __future__ import annotations

import json

import pytest

from zyko.fixer.engine import FixerEngine
from zyko.fixer.report import (
    fix_result_to_json,
    fix_result_to_text,
    fix_results_to_json,
    fix_results_to_text,
    fix_rules_table_text,
    fix_summary_line,
    severity_breakdown,
)

ENGINE = FixerEngine()

SAMPLE = "import os\n\ndef f(v):\n    return v == None\n"


# ----------------------------------------------------------- التقارير
def make_result():
    return ENGINE.fix_source(SAMPLE, "r.py")


def test_json_deterministic_bytes():
    a = fix_result_to_json(make_result())
    b = fix_result_to_json(make_result())
    assert a == b


def test_json_payload_structure():
    d = json.loads(fix_result_to_json(make_result()))
    assert d["schema"] == "zyko.fix/1"
    assert d["path"] == "r.py"
    assert d["changed"] is True
    assert isinstance(d["outcomes"], list) and d["outcomes"]
    for o in d["outcomes"]:
        assert o["suggestion_ar"]
        assert o["status"] in ("fixed", "manual", "open")
        assert o["status_ar"]
        assert o["action_ar"]


def test_text_report_sections():
    t = fix_result_to_text(make_result())
    assert "الملف: r.py" in t
    assert "أُصلح آليًا" in t
    assert "[أُصلح آليًا]" in t
    assert "[يدوي]" in t
    assert "الإجراء:" in t
    assert "الإصلاح:" in t
    assert "السبب:" in t


def test_text_report_parse_error():
    r = ENGINE.fix_source("def broken(:\n", "x.py")
    t = fix_result_to_text(r)
    assert "غير قابل للإصلاح" in t


def test_batch_report_and_summary_line():
    results = [make_result(), ENGINE.fix_source("x = 1\n", "c.py")]
    text = fix_results_to_text(results)
    assert "إصلاح 2 ملفًا" in text
    line = fix_summary_line(results)
    assert "الملفات: 2" in line


def test_batch_json_summary():
    payload = json.loads(fix_results_to_json([make_result()]))
    assert payload["summary"]["files"] == 1
    assert payload["files"][0]["path"] == "r.py"


def test_rules_table_lists_all_38():
    t = fix_rules_table_text()
    auto_rows = sum(1 for ln in t.splitlines() if "| آلي |" in ln)
    manual_rows = sum(1 for ln in t.splitlines() if "| يدوي |" in ln)
    assert auto_rows == 12 and manual_rows == 26
    assert "R-ERR-001" in t and "R-QLT-209" in t
    assert "R-SEC-119" in t  # موجة ميزان


def test_severity_breakdown_arabic():
    assert severity_breakdown({}) == "لا شيء"
    assert "حرج 2" in severity_breakdown({"critical": 2})


# --------------------------------------------------------------- CLI
def run_cli(capsys, *argv):
    from zyko.fixer.__main__ import main

    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


@pytest.fixture()
def defective(tmp_path):
    p = tmp_path / "def.py"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_cli_fix_dry_run_text(defective, capsys):
    code, out = run_cli(capsys, "fix", "--path", str(defective))
    assert code == 0
    assert "[أُصلح آليًا]" in out
    assert defective.read_text(encoding="utf-8") == SAMPLE  # تجريبي لا يكتب


def test_cli_fix_json(defective, capsys):
    code, out = run_cli(capsys, "fix", "--path", str(defective), "--format", "json")
    assert code == 0
    d = json.loads(out)
    assert d["schema"] == "zyko.fix/1"


def test_cli_fix_summary(defective, capsys):
    code, out = run_cli(capsys, "fix", "--path", str(defective), "--format", "summary")
    assert code == 0 and "أُصلح آليًا" in out


def test_cli_fix_write_then_check_clean(defective, capsys):
    run_cli(capsys, "fix", "--path", str(defective), "--write")
    assert "import os" not in defective.read_text(encoding="utf-8")
    code, _ = run_cli(capsys, "check", "--path", str(defective))
    assert code == 0


def test_cli_check_flags_remaining(tmp_path, capsys):
    p = tmp_path / "raw.py"
    p.write_text(SAMPLE, encoding="utf-8")
    code, _ = run_cli(capsys, "check", "--path", str(p))
    assert code == 1


def test_cli_check_clean_file(tmp_path, capsys):
    p = tmp_path / "clean.py"
    p.write_text("def f(v):\n    '''موثقة.'''\n    return v\n", encoding="utf-8")
    code, _ = run_cli(capsys, "check", "--path", str(p))
    assert code == 0


def test_cli_rules(capsys):
    code, out = run_cli(capsys, "rules")
    assert code == 0 and "R-ERR-001" in out and "R-QLT-209" in out


def test_cli_fix_diff_option(defective, capsys):
    code, out = run_cli(capsys, "fix", "--path", str(defective), "--diff")
    assert code == 0
    assert "(قبل)" in out and "(بعد)" in out


def test_cli_rules_filter(defective, capsys):
    code, _ = run_cli(
        capsys, "fix", "--path", str(defective), "--rules", "R-QLT-206", "--format", "summary"
    )
    assert code == 0
    assert "import os" in defective.read_text(encoding="utf-8")  # 207 مقيّد خارجًا


def test_cli_missing_path_usage_error(capsys):
    code, _ = run_cli(capsys, "fix", "--path", "/لا/يوجد/إطلاقًا.py")
    assert code == 2


def test_cli_check_missing_path(capsys):
    code, _ = run_cli(capsys, "check", "--path", "/لا/يوجد/إطلاقًا.py")
    assert code == 2


def test_cli_fix_folder(tmp_path, capsys):
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    code, out = run_cli(capsys, "fix", "--path", str(tmp_path), "--format", "summary")
    assert code == 0 and "الملفات: 2" in out


def test_cli_empty_folder_usage_error(tmp_path, capsys):
    empty = tmp_path / "فارغ"
    empty.mkdir()
    code, _ = run_cli(capsys, "fix", "--path", str(empty))
    assert code == 2
