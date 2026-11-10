"""المكوّن 5 — بوابة swarm: مهام متوازية بحد أعلى، نتائج حتمية (~30 اختباراً).

المحاور: التحقق من المدخل، ترتيب النتائج بترتيب المدخل مهما تباين التوازي،
العزل (فشل مهمة لا يحرق السرب)، الإكراه على dry-run بلا كتابة، إيصال السرب
وسلسلة بصماته، الحتمية (مقارنة كنسية + 100 تشغيل — P6)، والتسلسل والتجمد.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.exceptions import ConfigError
from zyko.orchestrator import classify, route, swarm
from zyko.orchestrator.classify import TaskType
from zyko.orchestrator.run import chain_hash_of
from zyko.orchestrator.swarm import MAX_PARALLEL_CAP, _canonical


@pytest.fixture()
def review_target(tmp_path: Path) -> Path:
    """ملف به عيوب معروفة للمراجعة الحتمية — قراءة فقط."""
    f = tmp_path / "widget.py"
    f.write_text(
        "import os\n\n\ndef probe(x):\n    return eval(x)\n",
        encoding="utf-8",
    )
    return f


# ------------------------------------------------------------------ التحقق من المدخل
class TestValidation:
    def test_empty_tasks_raises_arabic(self):
        with pytest.raises(ConfigError) as err:
            swarm([])
        assert "لا مهام" in str(err.value)

    @pytest.mark.parametrize("bad", [0, -1, -7])
    def test_max_parallel_below_one_raises_arabic(self, bad: int):
        with pytest.raises(ConfigError) as err:
            swarm(["مرحبا"], max_parallel=bad)
        assert "حد التوازي" in str(err.value)

    def test_max_parallel_clamped_to_cap(self):
        """حد أعلى معلن يحمي المنصات الضعيفة — لا خيوط بلا سقف."""
        result = swarm(["هدف مجهول واحد"] * (MAX_PARALLEL_CAP + 4), max_parallel=999)
        assert result.max_parallel == MAX_PARALLEL_CAP

    def test_max_parallel_clamped_to_task_count(self):
        result = swarm(["هدف مجهول"], max_parallel=8)
        assert result.max_parallel == 1


# ------------------------------------------------------------------ ترتيب النتائج
class TestOrderPreservation:
    def test_results_in_input_order_under_parallelism(self, review_target: Path):
        goals = [
            f"راجع {review_target}",
            "الجو جميل اليوم",
            f"راجع {review_target}",
            "هدف غير مفهوم تماماً",
        ]
        result = swarm(goals, max_parallel=4)
        assert [r.index for r in result.results] == [0, 1, 2, 3]
        assert [r.task for r in result.results] == goals

    def test_order_same_for_any_parallelism(self, review_target: Path):
        """القرار والنتائج لا يتغيران بالتوازي — بصمات المهام نفسها مهما كان
        حد التوازي؛ إيصال السرب وحده يوثّق إعداده (max_parallel) بأمانة."""
        goals = [f"راجع {review_target}", "مهمة مجهولة", f"راجع {review_target}"]
        task_payloads = set()
        for mp in (1, 2, 3, 8):
            result = swarm(goals, max_parallel=mp)
            task_payloads.add(_canonical([r.to_dict() for r in result.results]))
            assert [r.index for r in result.results] == [0, 1, 2]
        assert len(task_payloads) == 1


# ------------------------------------------------------------------ القرار داخل المهمة
class TestTaskSemantics:
    def test_unknown_goal_empty_plan_with_note(self):
        """هدف مجهول: خطة فارغة — التنفيذ يبلّغ ok=False (عقد run: خطة بلا
        خطوات ليست نجاحاً)، والملاحظة العربية موثقة بلا استثناء ولا خطأ."""
        result = swarm(["الجو جميل اليوم"])
        r = result.results[0]
        assert r.ok is False
        assert r.error_ar is None  # بلا استثناء — الفشل موثق في الإيصال نفسه
        assert r.plan is not None
        assert r.plan.steps == ()
        assert r.plan.classification.task is TaskType.UNKNOWN
        assert "لم أفهم المهمة" in r.plan.notes_ar[0]

    def test_review_goal_runs_read_only_review(self, review_target: Path):
        result = swarm([f"راجع {review_target}"])
        r = result.results[0]
        assert r.ok is True
        assert r.classification is not None
        assert r.classification.task is TaskType.REVIEW
        assert r.run_result is not None
        assert r.run_result.receipt["kind"] == "orchestrator"

    def test_plan_passthrough_bypasses_classify(self):
        """خطة جاهزة تُنفَّذ كما هي — السرب لا يعيد التصنيف ولا يغيّر القرار
        (خطة مجهولة تعود ok=False بعقد run، والكائن نفسه بلا إعادة توجيه)."""
        plan = route(classify("الجو جميل"), context={})
        result = swarm([plan])
        r = result.results[0]
        assert r.task == "plan:#0"
        assert r.ok is False
        assert r.plan is plan  # نفس الكائن — بلا إعادة توجيه

    def test_mixed_goals_and_plans(self, review_target: Path):
        plan = route(classify(f"راجع {review_target}"), context={"path": str(review_target)})
        result = swarm([f"راجع {review_target}", plan])
        assert result.results[0].task == f"راجع {review_target}"
        assert result.results[1].task == "plan:#1"
        assert all(r.ok for r in result.results)


# ------------------------------------------------------------------ العزل والفشل
class TestIsolation:
    def test_failing_task_does_not_kill_the_swarm(self, tmp_path: Path):
        """مهمة فاشلة (مسار غير موجود) توثَّق في إيصالها داخلها، والبقية تكمل
        — السبب العربي في الخطوة الفاشلة، لا استثناء يحرق السرب."""
        late_file = tmp_path / "late.py"
        late_file.write_text("def ok():\n    return 1\n", encoding="utf-8")
        result = swarm(["راجع ملف_غير_موجود.py", f"راجع {late_file}"], max_parallel=2)
        assert result.ok is False
        r0, r1 = result.results
        assert r0.ok is False
        assert r0.error_ar is None  # لا استثناء — الفشل موثق في إيصال الخطوة
        step_err = r0.run_result.steps[0].error_ar
        assert step_err and "المسار غير موجود" in step_err
        assert r1.ok is True

    def test_swarm_ok_true_only_when_all_ok(self, review_target: Path):
        good = swarm([f"راجع {review_target}", f"راجع {review_target}"])
        assert good.ok is True

    def test_fail_count_consistent(self, review_target: Path):
        """مجهول = فشل موثق (عقد run: خطة فارغة ok=False) — العدّاد صادق."""
        result = swarm([f"راجع {review_target}", "راجع مفقود.py", "مجهول"])
        assert result.receipt["fail_count"] == 2
        assert result.receipt["ok_count"] == 1
        assert result.receipt["total"] == 3


# ------------------------------------------------------------------ الإكراه على dry-run
class TestForcedDryRun:
    def test_swarm_never_writes_anything(self, tmp_path: Path):
        """مهام كتابة نظرياً (fix) تُنفَّذ تجريبياً — لا ملف يُلمس إطلاقاً."""
        target = tmp_path / "fixable.py"
        target.write_text("x = 1\n\n\n\n\n\ny = 2\n", encoding="utf-8")
        before = target.read_text(encoding="utf-8")
        result = swarm([f"أصلح {target}"], max_parallel=1)
        assert target.read_text(encoding="utf-8") == before
        assert all(r.run_result.receipt["dry_run"] is True for r in result.results)

    def test_swarm_receipt_declares_dry_run(self, review_target: Path):
        result = swarm([f"راجع {review_target}"])
        assert result.receipt["dry_run"] is True


# ------------------------------------------------------------------ إيصال السرب
class TestSwarmReceipt:
    def test_receipt_structure_stable_keys(self, review_target: Path):
        receipt = swarm([f"راجع {review_target}", "مجهول"]).receipt
        assert set(receipt) == {
            "version",
            "kind",
            "ok",
            "dry_run",
            "max_parallel",
            "total",
            "ok_count",
            "fail_count",
            "tasks",
            "chain_hash",
        }
        assert receipt["version"] == 1
        assert receipt["kind"] == "swarm"

    def test_chain_hash_covers_task_receipts_in_order(self, review_target: Path):
        result = swarm([f"راجع {review_target}", "مجهول", f"راجع {review_target}"])
        inner = [
            r.run_result.receipt["chain_hash"] for r in result.results if r.run_result is not None
        ]
        assert result.receipt["chain_hash"] == chain_hash_of(inner)

    def test_fingerprint_is_sha256_of_receipt(self, review_target: Path):
        import hashlib

        result = swarm([f"راجع {review_target}", "مجهول"])
        expected = hashlib.sha256(_canonical(result.receipt).encode("utf-8")).hexdigest()
        assert result.fingerprint == expected


# ------------------------------------------------------------------ الحتمية P6
class TestDeterminism:
    def test_two_runs_canonical_identical(self, review_target: Path):
        """نفس المدخل = نفس الإيصال بالبايت؛ حد التوازي إعداد موثّق في
        مكانه وحده (receipt.max_parallel) ولا يلمس قراراً ولا نتيجة."""
        goals = [f"راجع {review_target}", "الجو جميل", f"راجع {review_target}"]
        a = swarm(goals, max_parallel=2).to_dict()
        b = swarm(goals, max_parallel=3).to_dict()
        assert a["results"] == b["results"]
        assert a["fingerprint"] != b["fingerprint"]  # الإعداد موثّق في البصمة
        for key in a["receipt"]:
            if key != "max_parallel":
                assert a["receipt"][key] == b["receipt"][key]

    def test_hundred_runs_same_fingerprint(self, review_target: Path):
        goals = [f"راجع {review_target}", "مجهول تماماً"]
        fp = swarm(goals, max_parallel=2).fingerprint
        assert all(swarm(goals, max_parallel=2).fingerprint == fp for _ in range(100))


# ------------------------------------------------------------------ التسلسل والتجمد
class TestSerialization:
    def test_to_dict_json_serializable(self, review_target: Path):
        d = swarm([f"راجع {review_target}"]).to_dict()
        assert isinstance(json.dumps(d, ensure_ascii=False), str)

    def test_to_dict_keys_stable(self, review_target: Path):
        d = swarm([f"راجع {review_target}"]).to_dict()
        assert set(d) == {"results", "max_parallel", "ok", "receipt", "summary_ar", "fingerprint"}

    def test_frozen_immutability(self, review_target: Path):
        result = swarm([f"راجع {review_target}"])
        with pytest.raises(Exception):  # noqa: B017 — الفئة المجمّدة ترفض الكتابة
            result.ok = False  # type: ignore[misc]
        r = result.results[0]
        with pytest.raises(Exception):  # noqa: B017
            r.index = 99  # type: ignore[misc]

    def test_exports_surface(self):
        import zyko.orchestrator as pkg

        assert {"SwarmResult", "TaskResult", "swarm"} <= set(pkg.__all__)


# ------------------------------------------------------------------ الملخص العربي
class TestSummaryAr:
    def test_summary_counts_and_mode(self, review_target: Path):
        result = swarm([f"راجع {review_target}", "راجع مفقود.py", "مجهول"])
        s = result.summary_ar
        assert "سرب حتمي" in s
        assert "نجحت 1 وفشلت 2" in s
        assert "بلا كتابة" in s

    def test_summary_mentions_parallel_bound(self, review_target: Path):
        result = swarm([f"راجع {review_target}"], max_parallel=1)
        assert f"بحد توازي {result.max_parallel}" in result.summary_ar
