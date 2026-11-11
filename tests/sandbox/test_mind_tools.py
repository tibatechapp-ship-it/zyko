"""اختبارات تكامل الحلقة الإدراكية مع الأدوات المعزولة — اختبارات حقيقية.

الفجوة الصادقة التي وثّقها 0.26.0 تُغلق هنا: جولة التحسين تشغّل اختبارات
حقيقية لا مُصلِحًا حتميًا فقط — والنتيجة بوابة موثقة في الإيصال وكل
محاولة موقّعة في سلسلة تدقيق واحدة.
"""

from __future__ import annotations

import sys

import pytest

from zyko.mind.loop import MindLoop
from zyko.sandbox.audit import AuditLog
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.session import ToolSession


def _tools(out, **kw):
    """جلسة أدوات جاهزة بإيصال تدقيق تحت مجلد الجلسة."""
    root = out if out.exists() else out.parent
    contract = PermissionContract.for_roots(root, allow_run_tests=True, **kw)
    return ToolSession(contract, AuditLog(out.parent / "audit.jsonl"))


def _interpreter() -> str:
    name = sys.executable.replace("\\", "/").split("/")[-1].replace(".exe", "")
    return name or "python"


GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


class TestStepUnit:
    """وحدة ``_run_real_tests`` على مجلدات معدّة — سريع وشامل."""

    def _loop(self, out, **kw):
        return MindLoop(tools=_tools(out, **kw))

    def test_no_tools_session_returns_none(self, tmp_path):
        assert MindLoop()._run_real_tests(tmp_path, write=True) is None

    def test_dry_run_documents_skip(self, tmp_path):
        (tmp_path / "test_x.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        step = self._loop(tmp_path)._run_real_tests(tmp_path, write=False)
        assert step is not None and step.ok and step.exit_code == 0
        assert "تشغيل جاف" in step.details_ar

    def test_no_test_files_documents_honestly(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        step = self._loop(tmp_path)._run_real_tests(tmp_path, write=True)
        assert step.ok
        assert "لا ملفات اختبار" in step.details_ar

    def test_missing_out_dir_documents(self, tmp_path):
        step = self._loop(tmp_path)._run_real_tests(tmp_path / "مفقود", write=True)
        assert step.ok and "لا مجلد ناتج" in step.details_ar

    def test_green_tests_pass_gate(self, tmp_path):
        (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        step = self._loop(tmp_path)._run_real_tests(tmp_path, write=True)
        assert step.ok and step.exit_code == 0
        assert "خضراء" in step.details_ar
        assert step.step == "tools"

    def test_red_tests_fail_gate(self, tmp_path):
        (tmp_path / "test_bad.py").write_text(
            "def test_bad():\n    assert 1 == 2\n", encoding="utf-8"
        )
        step = self._loop(tmp_path)._run_real_tests(tmp_path, write=True)
        assert not step.ok
        assert step.exit_code not in (0, 2)
        assert "حمراء" in step.details_ar

    def test_runner_hijack_refused_in_loop(self, tmp_path):
        """pytest.py المختطف يُرفض قبل التنفيذ حتى داخل الحلقة."""
        (tmp_path / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        (tmp_path / "pytest.py").write_text("print('خطف')\n", encoding="utf-8")
        step = self._loop(tmp_path)._run_real_tests(tmp_path, write=True)
        assert not step.ok and "يظلّل" in step.details_ar

    def test_audit_chain_grows_and_verifies(self, tmp_path):
        out = tmp_path / "proj"
        out.mkdir()
        (out / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        session = ToolSession(
            PermissionContract.for_roots(tmp_path, allow_run_tests=True),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        MindLoop(tools=session)._run_real_tests(out, write=True)
        log = AuditLog(tmp_path / "audit.jsonl")
        assert log.verify().ok and log.verify().count >= 2

    def test_derived_contract_has_no_patch(self, tmp_path):
        """عقد الاختبارات المشتق لا يحمل الرقعة — التشغيل لا يكتب."""
        loop = self._loop(tmp_path)
        contract = loop._tools_contract_for(tmp_path)
        assert contract.allow_run_tests is True
        assert contract.allow_patch is False


class TestFullLoop:
    """الحلقة الكاملة مع جلسة أدوات — سلوك متوافق وخلاصة موثقة."""

    def test_loop_without_tools_has_no_tools_step(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert "tools" not in [s.step for s in receipt.steps]

    def test_loop_with_tools_runs_end_to_end(self, tmp_path):
        """حلقة كاملة بجلسة أدوات — التكامل لا ينكسر ولا يخرج استثناء."""
        out = tmp_path / "proj"
        session = ToolSession(
            PermissionContract.for_roots(tmp_path, allow_run_tests=True),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        receipt = MindLoop(tools=session).run(GOAL, out)
        assert receipt.ok
        assert receipt.failed_step is None
        # المشروع المولّد بلا ملفات اختبار — الخطوة موثقة الصدقة لا مختفية
        tools_steps = [s for s in receipt.steps if s.step == "tools"]
        if tools_steps:
            assert all("لا ملفات اختبار" in s.details_ar or s.ok for s in tools_steps)
        # والتدقيق سليم إن كُتب
        audit_file = tmp_path / "audit.jsonl"
        if audit_file.is_file():
            assert AuditLog(audit_file).verify().ok

    def test_loop_tools_on_existing_code_unchanged(self, tmp_path):
        """مسار الكود القائم لا يتغير مع الأدوات — توثيق واحد صادق يبقى."""
        target = tmp_path / "app.py"
        target.write_text("def f( ):\n    x=1\n    return x\n", encoding="utf-8")
        session = ToolSession(
            PermissionContract.for_roots(tmp_path, allow_run_tests=True),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        receipt = MindLoop(tools=session).run(f"اصلح الملف {target}", tmp_path / "session")
        assert receipt.ok
        assert receipt.kind == "FIX"
        assert "tools" not in [s.step for s in receipt.steps]


class TestCLI:
    def test_cli_flag_registered(self):
        from zyko.mind.cli import register_to

        import argparse

        parser = argparse.ArgumentParser()
        register_to(parser.add_subparsers(dest="mind_cmd"))
        args = parser.parse_args(["run", "هدف", "-o", "مخرج", "--tools"])
        assert args.tools is True

    def test_cli_without_flag_defaults_false(self):
        import argparse

        from zyko.mind.cli import register_to

        parser = argparse.ArgumentParser()
        register_to(parser.add_subparsers(dest="mind_cmd"))
        args = parser.parse_args(["run", "هدف", "-o", "مخرج"])
        assert args.tools is False
