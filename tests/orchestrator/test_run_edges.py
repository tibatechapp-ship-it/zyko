"""اختبارات أطر run — الفروع الهامشية الموثقة التي كشفها قياس التغطية.

كل فرع هنا حالة موثقة في run.py نفسها: مدخلات ناقصة، ملفات غير موجودة،
إيصالات غير مقروءة، استثناءات المحرّس والأدوات المحقونة، وملخصات الخطوات.
حتمي بلا شبكة — الاستثناءات تُحقن بـ monkeypatch.
"""

from __future__ import annotations

import importlib
import subprocess
import types

import pytest

from zyko.orchestrator import Plan, Step, classify, run
from zyko.orchestrator.run import step_summary_ar

DAAD_INSTALL_HINT = "pip install git+https://github.com/tibatechapp-ship-it/daad.git"


def _daad_available() -> bool:
    try:
        return (
            subprocess.run(  # nosec B607
                ["python", "-m", "daad", "version"], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


daad_required = pytest.mark.skipif(not _daad_available(), reason="daad not installed")

# وحدة run نفسها (الاسم `run` المُصدَّر من الحزمة هو الدالة لا الوحدة)
RUN_MOD = importlib.import_module("zyko.orchestrator.run")

HELLO_DAAD = 'اطبع("مرحبا من ضاد")\n'


def _plan_one(tool: str, **args) -> Plan:
    """خطة بخطوة واحدة — تُغطي فروع الأدوات مباشرة دون التوجيه."""
    return Plan(
        classification=classify("راجع الهدف"),
        steps=(Step(tool, dict(args)),),
        estimated_cost=None,
        notes_ar=(),
    )


# ------------------------------------------------------------------ مراجعة
class TestReviewEdges:
    def test_review_without_path_fails_arabic(self):
        result = run(_plan_one("review"))
        assert not result.ok
        assert result.steps[0].error_ar == "لم يُحدد مسار للمراجعة"

    def test_review_directory_reports_files_and_count(self, tmp_path):
        d = tmp_path / "pkg"
        d.mkdir()
        (d / "a.py").write_text("x = 1\n", encoding="utf-8")
        (d / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
        result = run(_plan_one("review", path=str(d)))
        assert result.ok
        out = result.steps[0].output
        assert out["count"] == 2 and len(out["files"]) == 2
        assert step_summary_ar(out) == "رُوجع 2 ملفاً"


# ------------------------------------------------------------------ إصلاح
class TestFixEdges:
    def test_fix_without_path_fails_arabic(self):
        result = run(_plan_one("fix"))
        assert not result.ok
        assert result.steps[0].error_ar == "لم يُحدد مسار للإصلاح"

    def test_fix_missing_path_fails_arabic(self, tmp_path):
        result = run(_plan_one("fix", path=str(tmp_path / "ghost.py")))
        assert not result.ok
        assert "المسار غير موجود" in result.steps[0].error_ar

    def test_fix_parse_error_refuses_structurally(self, tmp_path):
        target = tmp_path / "bad.py"
        target.write_text("def broken(:\n    pass\n", encoding="utf-8")
        result = run(_plan_one("fix", path=str(target)))
        assert not result.ok
        assert "تعذر الإصلاح" in result.steps[0].error_ar

    def test_fix_clean_file_reports_nothing_to_fix(self, tmp_path):
        target = tmp_path / "clean.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = run(_plan_one("fix", path=str(target)))
        assert result.ok
        out = result.steps[0].output
        assert out["changed"] is False
        assert "لا يوجد ما يُصلَح آلياً" in out["note_ar"]


# ------------------------------------------------------------------ توليد
class TestGenerateEdges:
    def test_generate_without_description_fails_arabic(self):
        result = run(_plan_one("generate"))
        assert not result.ok
        assert result.steps[0].error_ar == "لم يُحدد وصف المشروع"

    def test_generate_invalid_plan_fails_arabic(self, monkeypatch):
        monkeypatch.setattr("zyko.coder.plan.ProjectPlan.validate", lambda self: ["مشكلة اختبار"])
        result = run(_plan_one("generate", description="مشروع اختبار الفروع"))
        assert not result.ok
        assert "مخطط توليد غير صالح" in result.steps[0].error_ar
        assert "مشكلة اختبار" in result.steps[0].error_ar

    def test_generate_apply_with_custom_out(self, tmp_path):
        out = tmp_path / "custom-root"
        result = run(_plan_one("generate", description="مشروع الفروع", out=str(out)), dry_run=False)
        assert result.ok
        out_map = result.steps[0].output
        assert out_map["applied"] is True
        assert out_map["root"] == str(out)
        assert len(out_map["files"]) > 0


# ------------------------------------------------------------------ ترجمة
class TestTranspileEdges:
    def test_transpile_without_file_fails_arabic(self):
        result = run(_plan_one("transpile"))
        assert not result.ok
        assert result.steps[0].error_ar == "لم يُحدد ملف ضاد"

    def test_transpile_missing_file_fails_arabic(self, tmp_path):
        result = run(_plan_one("transpile", file=str(tmp_path / "ghost.daad")))
        assert not result.ok
        assert "الملف غير موجود" in result.steps[0].error_ar

    def test_transpile_subprocess_oserror_documented(self, tmp_path, monkeypatch):
        src = tmp_path / "hello.daad"
        src.write_text(HELLO_DAAD, encoding="utf-8")

        def boom(*_a, **_k):
            raise OSError("no exec")

        monkeypatch.setattr(subprocess, "run", boom)
        result = run(_plan_one("transpile", file=str(src)))
        assert not result.ok
        assert "تعذر تشغيل مترجم ضاد: OSError" in result.steps[0].error_ar

    def test_transpile_nonzero_exit_records_detail(self, tmp_path, monkeypatch):
        src = tmp_path / "hello.daad"
        src.write_text(HELLO_DAAD, encoding="utf-8")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: types.SimpleNamespace(returncode=2, stdout="", stderr="boom"),
        )
        result = run(_plan_one("transpile", file=str(src)))
        assert not result.ok
        assert "فشل مترجم ضاد (exit 2)" in result.steps[0].error_ar
        assert "boom" in result.steps[0].error_ar

    def test_transpile_nonzero_exit_without_detail(self, tmp_path, monkeypatch):
        src = tmp_path / "hello.daad"
        src.write_text(HELLO_DAAD, encoding="utf-8")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: types.SimpleNamespace(returncode=3, stdout="", stderr=""),
        )
        result = run(_plan_one("transpile", file=str(src)))
        assert not result.ok
        assert result.steps[0].error_ar == "فشل مترجم ضاد (exit 3)"

    @daad_required
    def test_transpile_real_dry_run_returns_code(self, tmp_path):
        src = tmp_path / "hello.daad"
        src.write_text(HELLO_DAAD, encoding="utf-8")
        result = run(_plan_one("transpile", file=str(src)))
        assert result.ok
        out = result.steps[0].output
        assert "اطبع(" in out["code"]
        assert out["bytes"] == len(out["code"])
        assert "لم يُكتب أي ملف" in out["dry_run_ar"]


# ------------------------------------------------------------------ تحقق
class TestVerifyEdges:
    def test_verify_without_receipt_fails_arabic(self):
        result = run(_plan_one("verify"))
        assert not result.ok
        assert result.steps[0].error_ar == "لم يُحدد مسار الإيصال"

    def test_verify_missing_file_fails_arabic(self, tmp_path):
        result = run(_plan_one("verify", receipt=str(tmp_path / "ghost.json")))
        assert not result.ok
        assert "الملف غير موجود" in result.steps[0].error_ar

    def test_verify_unreadable_json_fails_arabic(self, tmp_path):
        target = tmp_path / "broken.json"
        target.write_text("{ليس JSON", encoding="utf-8")
        result = run(_plan_one("verify", receipt=str(target)))
        assert not result.ok
        assert "إيصال غير مقروء" in result.steps[0].error_ar

    def test_verify_router_receipt_roundtrip(self, tmp_path, capsys):
        from zyko.cli import main

        receipt = tmp_path / "r.json"
        assert main(["ask", "--demo", "اختبار", "--receipt", str(receipt)]) == 0
        result = run(_plan_one("verify", receipt=str(receipt)))
        assert result.ok
        out = result.steps[0].output
        assert out["ok"] is True
        assert step_summary_ar(out) == "الإيصال صالح"


# ------------------------------------------------------------------ الملخصات
class TestStepSummaryBranches:
    def test_fix_applied_summary(self):
        s = step_summary_ar({"fixed": 2, "score_before": 60, "score_after": 80, "applied": True})
        assert s == "أُصلح 2 ملاحظة — الدرجة 60→80"

    def test_would_fix_summary(self):
        assert step_summary_ar({"would_fix": 3}) == "سيُصلَح 3 ملاحظة"

    def test_tree_summary(self):
        s = step_summary_ar({"files": {"a.py": 1, "b.py": 2, "c.py": 3}, "total_bytes": 77})
        assert s == "شجرة 3 ملفاً (77 بايت)"

    def test_code_summary(self):
        assert step_summary_ar({"code": "print()", "bytes": 5}) == "ترجمة تمت (5 بايت)"

    def test_verdict_passthrough(self):
        assert step_summary_ar({"verdict_ar": "المراجعة نظيفة"}) == "المراجعة نظيفة"

    def test_receipt_ok_summary(self):
        assert step_summary_ar({"ok": True}) == "الإيصال صالح"
        assert step_summary_ar({"ok": False}) == "الإيصال غير صالح"

    def test_fallback_summary(self):
        assert step_summary_ar({}) == "أُنجزت"
        assert step_summary_ar(None) == "أُنجزت"


# ------------------------------------------------------------------ run: بوابات المحرّس والأدوات
class TestRunGuardAndToolEdges:
    def test_guardian_exception_stops_plan_documented(self, monkeypatch):
        def boom(_proposal):
            raise RuntimeError("gate exploded")

        monkeypatch.setattr(RUN_MOD, "_guardian_verdict", boom)
        result = run(_plan_one("review", path="x.py"))
        assert not result.ok
        assert "تعذر تشغيل المحرّس: RuntimeError" in result.steps[0].error_ar
        assert result.steps[0].guardian_verdict == "REVIEW"

    def test_unknown_guardian_verdict_stops_plan(self, monkeypatch):
        monkeypatch.setattr(RUN_MOD, "_guardian_verdict", lambda _p: ("WEIRD", "سبب"))
        result = run(_plan_one("review", path="x.py"))
        assert not result.ok
        assert "حكم محرّس غير معروف: 'WEIRD'" in result.steps[0].error_ar

    def test_tool_exception_documented_not_raised(self, tmp_path, monkeypatch):
        target = tmp_path / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")

        def explode(_step, _dry):
            raise RuntimeError("tool exploded")

        monkeypatch.setitem(RUN_MOD._RUNNERS, "review", explode)
        result = run(_plan_one("review", path=str(target)))
        assert not result.ok
        assert "استثناء داخل الأداة: RuntimeError: tool exploded" in result.steps[0].error_ar
