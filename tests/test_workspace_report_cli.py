"""اختبارات مخرجات zyko.workspace: JSON/نص حتمي + واجهة سطر الأوامر.

العقد المُختبر هنا:
- JSON قابل للتحليل، مخططه zyko.workspace/1، وبلا زمن إلا عند الطلب
- التقرير النصي عربي ويعرض suggestion_ar لكل ملاحظة وسبب كل تخطٍ
- أكواد الخروج: 0 سليم، 1 ملاحظات متبقية، 2 خطأ استخدام أو فشل مهيكل
- سطر الأوامر لا يكتب شيئًا بلا إذن: --out أو --in-place مع --yes
"""

from __future__ import annotations

import json

from zyko.workspace.__main__ import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main
from zyko.workspace.engine import WorkspaceEngine
from zyko.workspace.report import (
    workspace_payload_summary,
    workspace_promise_text,
    workspace_result_to_json,
    workspace_result_to_text,
    workspace_summary_line,
)

BUGGY = """import os


def flip(flag):
    return flag == None


retry = lambda n: n - 1
"""

CLEAN = '''"""نظيف."""


def add(a: int, b: int) -> int:
    """يجمع."""
    return a + b
'''


def _plant(tmp_path, files: dict[str, str], name: str = "proj"):
    src = tmp_path / name
    src.mkdir()
    for rel, content in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return src


# ------------------------------------------------------------- JSON
def test_json_is_loadable_and_deterministic(tmp_path):
    a = _plant(tmp_path, {"m.py": BUGGY}, name="أ")
    b = _plant(tmp_path, {"m.py": BUGGY}, name="ب")
    r1, r2 = WorkspaceEngine().run(a), WorkspaceEngine().run(b)
    j1, j2 = workspace_result_to_json(r1), workspace_result_to_json(r2)
    assert json.loads(j1)["schema"] == "zyko.workspace/1"
    d1, d2 = json.loads(j1), json.loads(j2)
    d1["src"] = d2["src"] = ""
    assert d1 == d2
    assert "seconds" not in d1


def test_json_timing_only_on_request(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    r = WorkspaceEngine().run(src)
    assert "seconds" in json.loads(workspace_result_to_json(r, include_timing=True))


# ------------------------------------------------------------- النص
def test_text_report_shows_everything(tmp_path):
    src = _plant(tmp_path, {"وحدة.py": BUGGY})
    # ملف بترميز غير UTF-8 لاختبار سطر التخطي
    (src / "ملف-عتيق.py").write_bytes("x = 1\n".encode("utf-16"))
    r = WorkspaceEngine().run(src)
    text = workspace_result_to_text(r)
    assert "المحرك على أرض الواقع" in text
    assert "الإصلاح:" in text
    assert "وحدة.py" in text
    assert "تُخُطّي" in text and "UTF-8" in text
    assert r.verdict_ar in text or "الحكم" in text


def test_text_report_failure_shape(tmp_path):
    r = WorkspaceEngine().run(tmp_path / "لا-يوجد")
    text = workspace_result_to_text(r)
    assert "فشل المحرك" in text
    assert "السبب:" in text
    assert r.error_ar in text


def test_summary_line_ok_and_failure(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    r = WorkspaceEngine().run(src)
    line = workspace_summary_line(r)
    assert "فُحص" in line and "الحكم:" in line
    bad = WorkspaceEngine().run(tmp_path / "لا-يوجد")
    assert "فشل" in workspace_summary_line(bad)


def test_payload_summary_fields(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    s = workspace_payload_summary(WorkspaceEngine().run(src))
    for key in ("schema", "ok", "reviewed", "skipped", "fixed", "manual", "open", "verdict_ar"):
        assert key in s


def test_promise_text_mentions_guarantees():
    text = workspace_promise_text()
    assert "zyko.workspace/1" in text
    assert "38 قاعدة" in text and "12 مسارًا" in text
    assert "لا شيء افتراضيًا" in text


# ------------------------------------------------------------- CLI
def test_cli_run_json_dry_writes_nothing(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    before = {p: p.read_bytes() for p in src.rglob("*.py")}
    code = main(["run", "--src", str(src), "--format", "json"])
    assert code in (EXIT_OK, EXIT_FINDINGS)
    assert {p: p.read_bytes() for p in src.rglob("*.py")} == before


def test_cli_run_default_is_dry_and_exit_findings(tmp_path, capsys):
    src = _plant(
        tmp_path,
        {
            "m.py": BUGGY,
            "risky.py": 'def risky(expr):\n    """يُبقى بلا إصلاح آلي."""\n    return eval(expr)\n',
        },
    )
    before = {p: p.read_bytes() for p in src.rglob("*.py")}
    code = main(["run", "--src", str(src)])
    captured = capsys.readouterr()
    assert code == EXIT_FINDINGS  # ملاحظات يدوية متبقية
    assert "الإصلاح:" in captured.out
    assert {p: p.read_bytes() for p in src.rglob("*.py")} == before


def test_cli_run_clean_project_exits_zero(tmp_path):
    src = _plant(tmp_path, {"clean.py": CLEAN})
    assert main(["run", "--src", str(src)]) == EXIT_OK


def test_cli_run_missing_dir_exits_two(tmp_path, capsys):
    code = main(["run", "--src", str(tmp_path / "لا-يوجد")])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "فشل المحرك" in captured.out


def test_cli_run_json_payload_valid(tmp_path, capsys):
    src = _plant(tmp_path, {"m.py": BUGGY})
    main(["run", "--src", str(src), "--format", "json"])
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == "zyko.workspace/1"
    assert all(o["suggestion_ar"] for f in d["per_file"] for o in f["outcomes"])


def test_cli_run_summary_format(tmp_path, capsys):
    src = _plant(tmp_path, {"m.py": BUGGY})
    main(["run", "--src", str(src), "--format", "summary"])
    assert "الحكم" in capsys.readouterr().out


def test_cli_out_writes_fixed_copy(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    out = tmp_path / "النسخة"
    code = main(["run", "--src", str(src), "--out", str(out), "--fail-under", "0"])
    assert code == EXIT_OK
    assert (out / "m.py").exists()


def test_cli_out_occupied_exits_two(tmp_path, capsys):
    src = _plant(tmp_path, {"m.py": BUGGY})
    out = tmp_path / "مشغول"
    out.mkdir()
    (out / "x.txt").write_text("لا تمسّني", encoding="utf-8")
    code = main(["run", "--src", str(src), "--out", str(out)])
    assert code == EXIT_USAGE
    assert "غير فارغ" in capsys.readouterr().err


def test_cli_inplace_requires_yes(tmp_path, capsys):
    src = _plant(tmp_path, {"m.py": BUGGY})
    code = main(["run", "--src", str(src), "--in-place"])
    assert code == EXIT_USAGE
    assert "--yes" in capsys.readouterr().err


def test_cli_inplace_with_yes_writes(tmp_path):
    src = _plant(tmp_path, {"m.py": BUGGY})
    code = main(["run", "--src", str(src), "--in-place", "--yes", "--fail-under", "0"])
    assert code == EXIT_OK
    assert "retry = lambda" not in (src / "m.py").read_text(encoding="utf-8")


def test_cli_inplace_and_out_together_exits_two(tmp_path, capsys):
    src = _plant(tmp_path, {"m.py": BUGGY})
    code = main(["run", "--src", str(src), "--in-place", "--yes", "--out", str(tmp_path / "x")])
    assert code == EXIT_USAGE
    assert "لا كليهما" in capsys.readouterr().err


def test_cli_gate_command(tmp_path):
    assert main(["gate", "--max-seconds", "30"]) == EXIT_OK


def test_cli_promise_command(capsys):
    assert main(["promise"]) == EXIT_OK
    assert "zyko.workspace/1" in capsys.readouterr().out


def test_cli_exit_code_constants_match_convention():
    assert (EXIT_OK, EXIT_FINDINGS, EXIT_USAGE) == (0, 1, 2)
