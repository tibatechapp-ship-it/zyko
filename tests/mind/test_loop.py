"""اختبارات الحلقة الإدراكية الكاملة — إيصال حتمي وبوابات خمس وذاكرة."""

from __future__ import annotations

import json

from zyko.mind.core import ScriptedCore
from zyko.mind.global_memory import GlobalMemory
from zyko.mind.loop import MindLoop, MindReceipt
from zyko.mind.memory import MindMemory

GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


class TestHappyPath:
    def test_full_loop_green(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert receipt.ok
        assert receipt.failed_step is None
        assert receipt.kind == "GENERATE"
        assert receipt.plan_accepted
        steps = [s.step for s in receipt.steps]
        assert steps == ["perceive", "plan", "execute", "critic", "memory", "global-memory"]
        assert all(s.ok for s in receipt.steps)

    def test_generated_project_on_disk(self, tmp_path):
        out = tmp_path / "proj"
        MindLoop().run(GOAL, out)
        assert any(out.rglob("*.py"))

    def test_memory_written_with_state_and_lessons(self, tmp_path):
        out = tmp_path / "proj"
        MindLoop().run(GOAL, out)
        memory = MindMemory(out)
        state = memory.load_state()
        assert state["kind"] == "GENERATE"
        assert state["goal"] == GOAL
        assert memory.load_lessons()

    def test_fix_path_on_existing_file(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("def f( ):\n    x=1\n    return x\n", encoding="utf-8")
        receipt = MindLoop().run(f"اصلح الملف {target}", tmp_path / "session")
        assert receipt.ok
        assert receipt.kind == "FIX"
        assert receipt.rounds_ran == 1
        assert target.read_text(encoding="utf-8") != "def f( ):\n    x=1\n    return x\n"


class TestDeterminism:
    def test_same_goal_same_chain_hash(self, tmp_path):
        hashes = []
        for _ in range(2):
            out = tmp_path / "proj"
            receipt = MindLoop().run(GOAL, out)
            hashes.append(receipt.chain_hash)
            import shutil

            shutil.rmtree(out)
        assert hashes[0] == hashes[1]

    def test_receipt_json_deterministic(self, tmp_path):
        """الحتمية الكاملة: نفس الهدف ونفس البيئة ⇒ نفس الإيصال بالبايت.

        البيئة تشمل الذاكرة العابرة للجلسات — فتجدد بين الجولتين تحاكي
        بيئتين متطابقتين بالبايت. آثار الجلسات السابقة (seq الدفتر، الدروس
        المحملة) حالة بيئية موثقة خارج السلسلة: ``chain_hash`` متطابق دائمًا
        بين هدفين متطابقين مهما اختلف تاريخ الجهاز.
        """
        out = tmp_path / "proj"
        r1 = MindLoop().run(GOAL, out)
        j1 = r1.to_json()
        import shutil

        shutil.rmtree(out)
        shutil.rmtree(GlobalMemory().home)  # نفس البيئة: صفر ذاكرة عابرة
        r2 = MindLoop().run(GOAL, out)
        assert j1 == r2.to_json()
        assert r1.chain_hash == r2.chain_hash

    def test_chain_hash_64_hex(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert len(receipt.chain_hash) == 64
        int(receipt.chain_hash, 16)  # سداسي عشري صالح


class TestGuards:
    def test_non_string_goal_structural_fail(self, tmp_path):
        receipt = MindLoop().run(12345, tmp_path / "x")
        assert not receipt.ok
        assert receipt.failed_step == "goal"
        assert receipt.steps[0].exit_code == 2

    def test_empty_goal_structural_fail(self, tmp_path):
        receipt = MindLoop().run("   ", tmp_path / "x")
        assert not receipt.ok
        assert receipt.failed_step == "goal"

    def test_long_goal_structural_fail(self, tmp_path):
        receipt = MindLoop().run("وصف" * 3000, tmp_path / "x")
        assert not receipt.ok
        assert receipt.failed_step == "goal"

    def test_non_empty_out_dir_rejected_no_deletion(self, tmp_path):
        out = tmp_path / "busy"
        out.mkdir()
        (out / "keep.txt").write_text("لا تُحذف", encoding="utf-8")
        receipt = MindLoop().run(GOAL, out)
        assert not receipt.ok
        assert receipt.failed_step == "goal"
        assert (out / "keep.txt").read_text(encoding="utf-8") == "لا تُحذف"

    def test_unknown_task_rejected_before_any_writes(self, tmp_path):
        out = tmp_path / "no"
        core = ScriptedCore({}, default="لن يُستشعر أبدًا")
        receipt = MindLoop(core).run("قائمة مهام عادية بلا أمر", out)
        assert not receipt.ok
        # حرس الإدراك يرفض مبكرًا — لا استشارة قلب ولا خطة، ولا كتابة إطلاقًا
        assert receipt.failed_step == "perceive"
        assert [s.step for s in receipt.steps] == ["perceive"]
        assert core.calls == 0
        assert "حرس الإدراك رفض الناتج" in receipt.steps[0].details_ar
        assert not out.exists()

    def test_pii_goal_rejected_at_plan_no_writes(self, tmp_path):
        out = tmp_path / "pii"
        receipt = MindLoop().run("انشئ مشروع — للتواصل 0501234567", out)
        assert not receipt.ok
        assert receipt.failed_step == "plan"
        assert not out.exists()

    def test_fix_without_target_file_rejected(self, tmp_path):
        receipt = MindLoop().run("اصلح الملف غير_الموجود_هنا.py", tmp_path / "s")
        assert not receipt.ok
        assert receipt.failed_step in ("plan", "execute")


class TestScriptedCore:
    def test_scripted_core_advisory_used(self, tmp_path):
        core = ScriptedCore(
            {"مشروع": "خطة مقترحة: قائمة مهام بسيطة مع واجهة سطر أوامر"}, default="فارغ"
        )
        receipt = MindLoop(core).run(GOAL, tmp_path / "proj")
        assert receipt.ok
        assert "خطة مقترحة" in receipt.plan_text

    def test_scripted_core_empty_rejected_at_plan(self, tmp_path):
        core = ScriptedCore({}, default="   ")
        receipt = MindLoop(core).run(GOAL, tmp_path / "proj")
        assert not receipt.ok
        assert receipt.failed_step == "plan"


class TestDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        out = tmp_path / "dry"
        receipt = MindLoop().run(GOAL, out, write=False)
        assert not out.exists()
        assert receipt.dry_run
        assert receipt.steps[-1].step == "global-memory"
        assert "تخطٍّ" in receipt.steps[-1].details_ar

    def test_dry_run_receipt_ok(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "dry", write=False)
        assert receipt.ok


class TestReceipt:
    def test_to_json_round_trip(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        data = json.loads(receipt.to_json())
        assert data["schema"] == "zyko.mind/receipt-v1"
        assert data["kind"] == "GENERATE"
        assert len(data["steps"]) == 6

    def test_to_md_readable(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        md = receipt.to_md()
        assert "إيصال الحلقة الإدراكية" in md
        assert receipt.goal in md

    def test_receipt_is_dataclass(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert isinstance(receipt, MindReceipt)

    def test_rounds_param_respected(self, tmp_path):
        receipt = MindLoop(rounds=3).run(GOAL, tmp_path / "proj")
        assert receipt.rounds == 3


class TestRefine:
    def test_refine_round_only_when_gaps(self, tmp_path):
        # المشروع المولَّد مثالي — لا جولة تحسين ثانية توثَّق إلا عند فجوات
        receipt = MindLoop(rounds=2).run(GOAL, tmp_path / "proj")
        assert "refine" not in [s.step for s in receipt.steps]

    def test_reflect_retry_recovers_from_pii_advisory(self, tmp_path):
        # قلب مزيّف يلصق بيانًا شخصيًا في الاستشارة مرة واحدة — البوابات ترفض،
        # فتنعكس الحلقة بملاحظة الدرس وتستشعر ثانية بنص نظيف تمرّ —
        # السلوك ذاتي التصحيح: البوابات تقرر، والانعكاس يعلم، والميزانية تحسب،
        # والقصة كلها موثقة في الإيصال.
        class OncePIICore:
            name = "once-pii"
            deterministic = False
            calls = 0

            def respond(self, request, *, context=""):
                self.calls += 1
                if self.calls == 1:
                    return "اتصل على 0501234567 للتنسيق"
                return "خطة نظيفة بعد التعلم من الدرس"

        core = OncePIICore()
        receipt = MindLoop(core, rounds=2).run(GOAL, tmp_path / "proj")
        assert receipt.ok
        assert core.calls == 2  # استشارة مرفوضة + استشارة ثانية بالدرس
        assert receipt.plan_accepted
        plan_attempts = [s for s in receipt.steps if s.step == "plan"]
        assert len(plan_attempts) == 2
        assert not plan_attempts[0].ok and plan_attempts[1].ok
        reflections = receipt.reflections
        assert len(reflections) == 1
        assert reflections[0]["stage"] == "plan"
        assert reflections[0]["retried"] is True
        assert "0501234567" not in json.dumps(reflections)  # الدرس لا يحمل البيان نفسه
        assert receipt.budget["used"].get("plan") == 1

    def test_reflect_budget_exhausted_documents_stop(self, tmp_path):
        # قلب يلصق بيانًا شخصيًا كل مرة — الميزانية تنفد والفشل موثق بلا تجاوز
        class AlwaysPIICore:
            name = "always-pii"
            deterministic = False
            calls = 0

            def respond(self, request, *, context=""):
                self.calls += 1
                return f"اتصل على 0501234567 للتنسيق (محاولة {self.calls})"

        core = AlwaysPIICore()
        receipt = MindLoop(core, rounds=2).run(GOAL, tmp_path / "proj")
        assert not receipt.ok
        assert receipt.failed_step == "plan"
        assert core.calls == 3  # محاولة أصلية + الميزانية الافتراضية 2 إعادة
        assert receipt.budget["used"].get("plan") == 2
        assert receipt.budget["total_used"] == 2
        assert not receipt.plan_accepted
        assert not (tmp_path / "proj").exists()


class TestNoNetwork:
    def test_loop_offline_by_default(self, tmp_path):
        """الحلقة الافتراضية تعمل بلا شبكة ولا مفاتيح — معيار إتمام المرحلة A."""
        import os

        saved = {
            k: os.environ.pop(k, None)
            for k in ("ZYKO_QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        }
        try:
            receipt = MindLoop().run(GOAL, tmp_path / "proj")
            assert receipt.ok
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
