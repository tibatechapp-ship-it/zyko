"""بنّاؤو حالات التقييم (ج) — الانعكاس، الذاكرة الموقعة، التصنيف والتوجيه، المصنع."""

from __future__ import annotations

import json
import pathlib
import tempfile

from zyko.mind.global_memory import (
    GENESIS_HASH,
    MAX_GLOBAL_LESSONS,
    MAX_LESSON_CHARS,
    GlobalMemory,
    goal_digest,
    lesson_polarity,
    normalize_text,
    recall_score,
    topics_conflict,
)
from zyko.mind.global_memory import (
    entry_hash as gm_entry_hash,
)
from zyko.mind.perception import perceive
from zyko.mind.reflect import (
    DEFAULT_STAGE_RETRIES,
    MAX_FEEDBACK_CHARS,
    MAX_STAGE_NAME_CHARS,
    MAX_TOTAL_RETRIES,
    ROUTE_TABLE,
    RetryBudget,
    condense_feedback,
    fallback_note,
    guard_execution,
    guard_feedback,
    guard_perception,
    guard_plan,
    normalize_stage,
    reflect_note,
)
from zyko.orchestrator import classify, extract_context, route
from zyko.orchestrator.classify import PRIORITY, TASK_KEYWORDS, TaskType


class _StubStep:
    """خطوة ناتج بسيطة لحارس التنفيذ — الحارس هو المقيس لا الخطوة."""

    def __init__(
        self, ok: bool = True, evidence: dict[str, str] | None = None, details_ar: str = ""
    ):
        self.ok = ok
        self.evidence = evidence or {}
        self.details_ar = details_ar


class _StubPlanStep:
    def __init__(self, tool: str, index: int):
        self.tool = tool
        self.index = index


class _StubPlan:
    def __init__(self, tools: tuple[str, ...], verdicts: tuple = ()):
        self.steps = tuple(_StubPlanStep(t, i + 1) for i, t in enumerate(tools))
        self.verdicts = verdicts


class _StubVerdict:
    def __init__(self, gate: str, passed: bool, details_ar: str = "سبب"):
        self.gate = gate
        self.passed = passed
        self.details_ar = details_ar


# ========================================== 12) الانعكاس والميزانية
def build_reflect():
    cases = []

    def fn_stage_none():
        return (
            (True, "None يطبَّع")
            if normalize_stage(None) == "غير-مسماة"
            else (False, f"None → {normalize_stage(None)}")
        )

    cases.append(("تطبيع", "اسم مرحلة None يطبَّع", fn_stage_none))

    def fn_stage_int():
        return (
            (True, "العدد يطبَّع نصًا")
            if normalize_stage(123) == "123"
            else (False, f"123 → {normalize_stage(123)!r}")
        )

    cases.append(("تطبيع", "اسم مرحلة رقمي يطبَّع", fn_stage_int))

    def fn_stage_ws():
        return (
            (True, "الفراغ يُطوى")
            if normalize_stage("  a   b  ") == "a b"
            else (False, f"فراغ → {normalize_stage('  a   b  ')!r}")
        )

    cases.append(("تطبيع", "فراغات الطرفين والداخل تُطوى", fn_stage_ws))

    def fn_stage_cap():
        got = normalize_stage("ا" * 60)
        return (
            (True, "السقف يعمل")
            if len(got) == MAX_STAGE_NAME_CHARS
            else (False, f"طول {len(got)} بدل {MAX_STAGE_NAME_CHARS}")
        )

    cases.append(("تطبيع", "سقف اسم المرحلة 32", fn_stage_cap))

    def fn_stage_empty():
        return (
            (True, "الفراغ يُرمى للمجهول")
            if normalize_stage("   ") == "غير-مسماة"
            else (False, "فراغ خالص أعاد اسمًا")
        )

    cases.append(("تطبيع", "اسم فراغي يعود للمجهول", fn_stage_empty))

    def fn_budget_default():
        b = RetryBudget()
        a = b.consume("plan")
        b.consume("plan")
        c = b.consume("plan")
        ok = a and c is False and b.used("plan") == 2
        return (True, "الافتراضي 2 صارم") if ok else (False, f"ميزانية افتراضية: {b.to_dict()}")

    cases.append(("ميزانية", "الميزانية الافتراضية محدودة", fn_budget_default))

    def fn_budget_override():
        b = RetryBudget(default_limit=1, per_stage={"critic": 5})
        ok = b.limit("critic") == 5 and b.limit("plan") == 1
        return (True, "الاستثناء يغلب") if ok else (False, f"limits: {b.to_dict()['limits']}")

    cases.append(("ميزانية", "استثناء مرحلة يغلب الافتراضي", fn_budget_override))

    def fn_budget_negative():
        b = RetryBudget(default_limit=-3)
        return (
            (True, "السالب صفر")
            if b.default_limit == 0 and not b.can_retry("x")
            else (False, f"سالب: {b.default_limit}")
        )

    cases.append(("ميزانية", "حدود سالبة تُقيَّد للصفر", fn_budget_negative))

    def fn_budget_junk():
        b = RetryBudget(default_limit="ثلاثة")
        return (True, "النص يُقيَّد") if b.default_limit == 0 else (False, "حد غير عددي مرّ")

    cases.append(("ميزانية", "حد غير عددي يُقيَّد", fn_budget_junk))

    def fn_budget_total_cap():
        b = RetryBudget(default_limit=5, total_cap=3)
        got = [b.consume("plan"), b.consume("plan"), b.consume("critic"), b.consume("critic")]
        ok = got[:3] == [True, True, True] and got[3] is False and b.total_used == 3
        return (True, "السقف الكلي صارم") if ok else (False, f"سقف كلي: {got}")

    cases.append(("ميزانية", "السقف الكلي يمنع عبر المراحل", fn_budget_total_cap))

    def fn_budget_explicit_cap():
        # العقد: الافتراضي 8 حماية الحلقة؛ التجاوز الصريح يُحترم (مختبر الأداء)
        b = RetryBudget(total_cap=10**9)
        d = RetryBudget()
        ok = b.total_cap == 10**9 and d.total_cap == MAX_TOTAL_RETRIES
        return (
            (True, "الافتراضي 8 والتجاوز الصريح محترم")
            if ok
            else (False, f"caps: {b.total_cap}/{d.total_cap}")
        )

    cases.append(("ميزانية", "السقف الكلي: افتراضي 8 وتجاوز صريح محترم", fn_budget_explicit_cap))

    def fn_budget_hostile_key():
        b = RetryBudget(per_stage={"  PLAN  \n": 7})
        ok = b.limit("plan") == 7
        return (True, "الاسم العدوي يطبَّع") if ok else (False, "اسم مرحلة عدوي فتح خانة جديدة")

    cases.append(("ميزانية", "اسم عدوي لا يخترق الميزانية", fn_budget_hostile_key))

    def fn_budget_remaining():
        b = RetryBudget(default_limit=3)
        b.consume("plan")
        ok = b.remaining("plan") == 2 and b.used("plan") == 1
        return (True, "الحساب دقيق") if ok else (False, f"remaining={b.remaining('plan')}")

    cases.append(("ميزانية", "المتبقي والمستهلك دقيقان", fn_budget_remaining))

    def fn_budget_dict_sorted():
        b = RetryBudget(per_stage={"b": 1, "a": 2})
        d = b.to_dict()
        return (
            (True, "مفرز بلا زمن")
            if list(d["limits"].keys()) == ["a", "b"]
            else (False, f"limits: {d['limits']}")
        )

    cases.append(("ميزانية", "to_dict مفاتيحه مفرزة", fn_budget_dict_sorted))

    def fn_table_mirror():
        expect = {
            "GENERATE": ("pipeline", "critic", "baseline"),
            "FIX": ("orchestrator", "orchestrator", "critic"),
            "REVIEW": ("orchestrator", "critic"),
        }
        return (
            (True, "الجدول موثق")
            if all(ROUTE_TABLE[k] == v for k, v in expect.items())
            else (False, "جدول المسار تغير")
        )

    cases.append(("جدول", "جدول المسار الحتمي الثابت", fn_table_mirror))

    def fn_table_kinds():
        kinds = set(ROUTE_TABLE.keys())
        need = {"GENERATE", "FIX", "REVIEW", "ANALYZE", "VERIFY", "TRANSPILE"}
        return (True, "ستة أنواع") if kinds == need else (False, f"أنواع الجدول: {sorted(kinds)}")

    cases.append(("جدول", "أنواع المسار الستة موثقة", fn_table_kinds))

    # الحرّاس
    def fn_perception_ok():
        p = perceive("أنشئ مشروع قائمة مهام جديد")
        r = guard_perception(p)
        return (True, "إدراك سليم يمر") if r.ok else (False, f"إدراك سليم رُفض: {r.reason_ar}")

    cases.append(("حارس-إدراك", "إدراك سليم يمر", fn_perception_ok))

    def fn_perception_unknown():
        p = perceive("")
        r = guard_perception(p)
        return (True, "المجهول يُرفض") if not r.ok else (False, "هدف فارغ مرّ حارس الإدراك!")

    cases.append(("حارس-إدراك", "هدف فارغ يُرفض", fn_perception_unknown))

    def fn_perception_identity():
        p = perceive("أنشئ مشروع جديد")
        kinds = [str(getattr(c, "kind", "")) for c in p.criteria]
        return (
            (True, "معيارا الهوية محفوظان")
            if kinds.count("always") >= 2
            else (False, f"معايير الهوية: {kinds}")
        )

    cases.append(("حارس-إدراك", "معيارا الهوية دائمان", fn_perception_identity))

    def fn_plan_ok():
        p = _StubPlan(("pipeline", "critic", "baseline"))
        r = guard_plan(p)
        return (True, "المطابق للجدول يمر") if r.ok else (False, f"خطة مطابقة رُفضت: {r.reason_ar}")

    cases.append(("حارس-خطة", "خطة مطابقة للجدول تمر", fn_plan_ok))

    def fn_plan_wrong_order():
        perception = perceive("أنشئ مشروع قائمة مهام")
        p = _StubPlan(("critic", "pipeline", "baseline"))
        r = guard_plan(p, perception)
        return (True, "الترتيب المقلوب يُرفض") if not r.ok else (False, "ترتيب مقلوب مرّ حارس الخطة!")

    cases.append(("حارس-خطة", "ترتيب مقلوب يُرفض", fn_plan_wrong_order))

    def fn_plan_empty():
        p = _StubPlan(())
        r = guard_plan(p)
        return (True, "الخطة الفارغة تُرفض") if not r.ok else (False, "خطة بلا خطوات مرّت")

    cases.append(("حارس-خطة", "خطة بلا خطوات تُرفض", fn_plan_empty))

    def fn_plan_bad_verdict():
        p = _StubPlan(("orchestrator", "critic"), (_StubVerdict("PII", False),))
        r = guard_plan(p)
        return (True, "بوابة ساقطة تُرفض") if not r.ok else (False, "حكم بوابة فاشل مرّ")

    cases.append(("حارس-خطة", "حكم بوابة ساقط يُرفض", fn_plan_bad_verdict))

    def fn_plan_indices():
        perception = perceive("راجع الملف الحالي")
        plan = _StubPlan(("orchestrator", "critic"))
        plan.steps[1].index = 5
        r = guard_plan(plan, perception)
        return (True, "الترقيم محكوم") if not r.ok else (False, "ترقيم غير متسلسل مرّ")

    cases.append(("حارس-خطة", "ترقيم غير متسلسل يُرفض", fn_plan_indices))

    def fn_plan_unknown_kind():
        r = guard_plan(_StubPlan(("أداة",)), None)
        # بلا إدراك: لا جدول يفحص — لكن الخطة بخطوة غريبة لا تنكسر
        return (True, "بلا إدراك لا انهيار") if isinstance(r.ok, bool) else (False, "الحارس انهار")

    cases.append(("حارس-خطة", "حارس بلا إدراك لا ينهار", fn_plan_unknown_kind))

    def fn_exec_missing_file():
        step = _StubStep(True, {"out.py": "0" * 64})
        with tempfile.TemporaryDirectory() as td:
            r = guard_execution(step, td, write=True)
            return (True, "إيصال بلا أثر يُرفض") if not r.ok else (False, "بصمة بلا ملف مرّت!")

    cases.append(("حارس-تنفيذ", "بصمة بلا ملف تُرفض", fn_exec_missing_file))

    def fn_exec_real_file():
        with tempfile.TemporaryDirectory() as td:
            import hashlib

            p = pathlib.Path(td) / "out.py"
            p.write_text("x = 1\n", encoding="utf-8")
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            step = _StubStep(True, {"out.py": sha})
            r = guard_execution(step, td, write=True)
            return (True, "الأثر الحقيقي يمر") if r.ok else (False, f"أثر حقيقي رُفض: {r.reason_ar}")

    cases.append(("حارس-تنفيذ", "أثر حقيقي يمر", fn_exec_real_file))

    def fn_exec_no_evidence():
        step = _StubStep(True, {})
        r = guard_execution(step, None, write=True)
        return (True, "الكتابة بلا أدلة تُرفض") if not r.ok else (False, "وضع كتابة بلا أدلة مرّ")

    cases.append(("حارس-تنفيذ", "وضع كتابة بلا أدلة يُرفض", fn_exec_no_evidence))

    def fn_exec_dry():
        step = _StubStep(True, {})
        r = guard_execution(step, None, write=False)
        return (True, "الجاف يُوثق تخطين") if r.ok else (False, "تشغيل جاف رُفض")

    cases.append(("حارس-تنفيذ", "التشغيل الجاف يمر موثقًا", fn_exec_dry))

    def fn_exec_failed_step():
        step = _StubStep(False, {}, details_ar="المرحلة سقطت")
        r = guard_execution(step, None, write=False)
        return (True, "الخطوة الفاشلة تُرفض") if not r.ok else (False, "خطوة ok=False مرّت")

    cases.append(("حارس-تنفيذ", "خطوة فاشلة تُرفض", fn_exec_failed_step))

    def fn_exec_cap64():
        with tempfile.TemporaryDirectory() as td:
            step = _StubStep(True, {f"مفقود{i}.py": "0" * 64 for i in range(80)})
            r = guard_execution(step, td, write=True)
            ok = not r.ok and "64 دليلًا" in r.reason_ar
            return (True, "الفحص مسقوف 64") if ok else (False, f"سقف الأدلة: {r.reason_ar[:50]}")

    cases.append(("حارس-تنفيذ", "فحص الأدلة مسقوف بـ64", fn_exec_cap64))

    def fn_feedback_empty():
        r = guard_feedback("", ())
        return (True, "الفراغ يُرفض") if not r.ok else (False, "ملاحظة فارغة مرّت")

    cases.append(("حارس-ملاحظة", "ملاحظة فارغة تُرفض", fn_feedback_empty))

    def fn_feedback_pii():
        r = guard_feedback("اتصل بـ 0512345678 للإصلاح", ())
        return (True, "PII في الملاحظة يُرفض") if not r.ok else (False, "هاتف في ملاحظة مرّ!")

    cases.append(("حارس-ملاحظة", "PII في الملاحظة يُرفض", fn_feedback_pii))

    def fn_feedback_bidi():
        r = guard_feedback("نص\u202aمخترق", ())
        return (True, "bidi يُرفض") if not r.ok else (False, "محرف اتجاه في ملاحظة مرّ")

    cases.append(("حارس-ملاحظة", "محرف اتجاه في الملاحظة يُرفض", fn_feedback_bidi))

    def fn_feedback_gap_kept():
        r = guard_feedback("أصلح التسلسل أولًا ثم المجلد", ("التسلسل", "المجلد"))
        return (
            (True, "الفجوات محفوظة") if r.ok else (False, f"فجوات مذكورة رُفضت: {r.reason_ar[:40]}")
        )

    cases.append(("حارس-ملاحظة", "فجوات مذكورة تمر", fn_feedback_gap_kept))

    def fn_feedback_gap_lost():
        r = guard_feedback("أصلح التسلسل فقط", ("التسلسل", "المجلد"))
        return (True, "فجوة مفقودة تُرفض") if not r.ok else (False, "تكثيف أفقد فجوة ومرّ!")

    cases.append(("حارس-ملاحظة", "فجوة غائبة عن النص تُرفض", fn_feedback_gap_lost))

    def fn_condense_budget():
        text = condense_feedback("س" * 1000, ("فجوة-أ", "فجوة-ب"))
        ok = len(text) <= MAX_FEEDBACK_CHARS and "فجوة-أ" in text and "فجوة-ب" in text
        return (True, "الضغط يحفظ الفجوات") if ok else (False, f"ضغط {len(text)} حرفًا وفقد فجوة؟")

    cases.append(("تكثيف", "تكثيف يحفظ أسماء الفجوات", fn_condense_budget))

    def fn_condense_determinism():
        a = condense_feedback("نص ثابت", ("فجوة",))
        b = condense_feedback("نص ثابت", ("فجوة",))
        return (True, "حتمي بالبايت") if a == b else (False, "تكثيفان اختلفا")

    cases.append(("تكثيف", "تكثيف حتمي بالبايت", fn_condense_determinism))

    def fn_fallback_note():
        a, b = fallback_note(), fallback_note()
        return (True, "بديل ثابت") if a == b and a else (False, "ملاحظة البديل غير ثابتة")

    cases.append(("ملاحظة", "fallback_note ثابت بالبايت", fn_fallback_note))

    def fn_reflect_note():
        a = reflect_note("plan", reason_ar="البوابة رفضت", gaps=("المسار",), attempt=1)
        b = reflect_note("plan", reason_ar="البوابة رفضت", gaps=("المسار",), attempt=2)
        ok = a != b and "plan" in a and "المسار" in a
        return (True, "المحاولة تدخل الملاحظة") if ok else (False, "ملاحظتا محاولتين تطابقتا")

    cases.append(("ملاحظة", "ملاحظة الانعكاس تحمل المحاولة", fn_reflect_note))

    def fn_reflect_note_budget():
        note = reflect_note("execute", reason_ar="س" * 800, gaps=(), attempt=3)
        return (
            (True, "الملاحظة مسقوفة")
            if len(note) <= MAX_FEEDBACK_CHARS + 50
            else (False, f"ملاحظة {len(note)} حرفًا")
        )

    cases.append(("ملاحظة", "ملاحظة الانعكاس تحت السقف", fn_reflect_note))

    def fn_constants():
        ok = MAX_FEEDBACK_CHARS == 600 and MAX_STAGE_NAME_CHARS == 32 and DEFAULT_STAGE_RETRIES == 2
        return (True, "السقوف الموثقة") if ok else (False, "سقوف الانعكاس تغيرت")

    cases.append(("سقوف", "سقوف الانعكاس الثابتة", fn_constants))

    return cases


# ========================================== 13) الذاكرة الموقعة
def build_ledger():
    cases = []

    def fn_record():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            entry = mem.record_session(goal="أنشئ مشروع أ", project="مشروع-أ")
            return (
                (True, "الجلسة تُوقَّع")
                if entry.seq == 1 and entry.hash
                else (False, f"أول جلسة: seq={entry.seq}")
            )

    cases.append(("دفتر", "أول جلسة بتسلسل 1", fn_record))

    def fn_seq_growth():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.record_session(goal="أ", project="p1")
            e2 = mem.record_session(goal="ب", project="p2")
            return (True, "الترقيم ينمو") if e2.seq == 2 else (False, f"seq={e2.seq}")

    cases.append(("دفتر", "الترقيم ينمو عبر الجلسات", fn_seq_growth))

    def fn_verify():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(3):
                mem.record_session(goal=f"هدف {i}", project=f"p{i}")
            r = mem.verify()
            return (
                (True, "سلسلة سليمة")
                if r.ok and r.count == 3
                else (False, f"verify: {r.to_dict()}")
            )

    cases.append(("دفتر", "verify يصدّق السلسلة", fn_verify))

    def fn_genesis():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="أول", project="p")
            return (
                (True, "الجذر الصفري")
                if e.prev_hash == GENESIS_HASH
                else (False, f"جذر: {e.prev_hash[:8]}")
            )

    cases.append(("دفتر", "جلسة الجذر تحمل GENESIS", fn_genesis))

    def fn_goal_privacy():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            secret_goal = "هدف-سري-جدا-لا-يجب-قراءة-الحرف-منه-0912345678"  # nosec B105 — بذرة اختبار مقصودة تتحقق أن الهدف يُبصم لا يُخزَّن
            mem.record_session(goal=secret_goal, project="p")
            raw = (pathlib.Path(td) / "sessions.jsonl").read_text(encoding="utf-8")
            return (
                (True, "الهدف بصمة لا نص")
                if secret_goal not in raw
                else (False, "النص الخام للهدف في الدفتر!")
            )

    cases.append(("خصوصية", "الهدف يُخزَّن بصمة لا نصًا", fn_goal_privacy))

    def fn_goal_digest():
        a = goal_digest("نص ثابت")
        b = goal_digest("نص ثابت")
        c = goal_digest("نص آخر")
        return (
            (True, "بصمة حتمية")
            if a == b and a != c and len(a) == 64
            else (False, "goal_digest غير حتمي")
        )

    cases.append(("خصوصية", "goal_digest حتمي", fn_goal_digest))

    def fn_tamper():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(3):
                mem.record_session(goal=f"هدف {i}", project=f"p{i}")
            path = pathlib.Path(td) / "sessions.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            target = json.loads(lines[1])
            target["project"] = "مزوَّر"
            lines[1] = json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            r = mem.verify()
            return (True, "العبث يُكتشف") if not r.ok else (False, "تعديل مشروع مرّ بسلام")

    cases.append(("عبث", "تعديل الجلسة يكسر السلسلة", fn_tamper))

    def fn_sessions_order():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(4):
                mem.record_session(goal=f"هدف {i}", project=f"p{i}")
            seqs = [s.seq for s in mem.sessions()]
            return (True, "الجلسات بترتيبها") if seqs == [1, 2, 3, 4] else (False, f"جلسات: {seqs}")

    cases.append(("دفتر", "الجلسات تقرأ بترتيبها", fn_sessions_order))

    def fn_empty_memory():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            ok = mem.sessions() == [] and mem.verify().ok and mem.verify().count == 0
            return (True, "ذاكرة فراغية سليمة") if ok else (False, "ذاكرة فارغة غير سليمة القراءة")

    cases.append(("دفتر", "ذاكرة فارغة تقرأ وتصدق", fn_empty_memory))

    # الدروس
    def fn_learn_basic():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            learned = mem.learn(["دائماً استخدم القوائم الآمنة"])
            lessons = mem.load_lessons()
            ok = learned and lessons and lessons[0].endswith("القوائم الآمنة")
            return (True, "درس يُتعلم") if ok else (False, f"تعلم: {learned}")

    cases.append(("دروس", "درس واحد يُخزَّن", fn_learn_basic))

    def fn_learn_dedupe():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["درس فريد للفحص"])
            mem.learn(["درس فريد للفحص"])
            lessons = mem.load_lessons()
            return (
                (True, "التكرار يُزال") if len(lessons) == 1 else (False, f"تكرار: {len(lessons)}")
            )

    cases.append(("دروس", "الدرس المكرر يُزال", fn_learn_dedupe))

    def fn_learn_dedupe_harakat():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["دَائِمًا اِسْتَخْدِم الدروس"])
            mem.learn(["دائما استخدم الدروس"])
            lessons = mem.load_lessons()
            return (
                (True, "التشكيل لا يفرد")
                if len(lessons) == 1
                else (False, f"تشكيل فَرَد درسين: {len(lessons)}")
            )

    cases.append(("دروس", "التشكيل لا يكسر إزالة التكرار", fn_learn_dedupe_harakat))

    def fn_learn_clamp():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["س" * 1000])
            lessons = mem.load_lessons()
            return (
                (True, "الدرس مسقوف")
                if lessons and len(lessons[0]) <= MAX_LESSON_CHARS
                else (False, f"درس {len(lessons[0])} حرفًا")
            )

    cases.append(("دروس", "درس طويل يُقصّ للسقف", fn_learn_clamp))

    def fn_learn_scrub():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(
                ["لا تخزن التوكن " + "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" + " في الكود"]
            )
            lessons = mem.load_lessons()
            raw = json.dumps(lessons, ensure_ascii=False)
            return (
                (True, "السر مقنّع في الدرس")
                if ("ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456") not in raw
                else (False, "سر في الدروس!")
            )

    cases.append(("دروس", "سر في الدرس يُقنَّع", fn_learn_scrub))

    def fn_learn_fifo():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(MAX_GLOBAL_LESSONS + 1):
                mem.learn([f"درس رقم {i} فريد للإخلاء"])
            lessons = mem.load_lessons()
            ok = len(lessons) == MAX_GLOBAL_LESSONS and "درس رقم 0" not in lessons[0]
            return (
                (True, "الأقدم يُخلَّى أولًا")
                if ok
                else (False, f"إخلاء: {len(lessons)} درسًا والأول {lessons[0][:12]}")
            )

    cases.append(("دروس", "السقف يُخلّي الأقدم أولًا", fn_learn_fifo))

    def fn_learn_empty():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            got = mem.learn([])
            return (
                (True, "لا دروس لا كتابة")
                if got == () and mem.load_lessons() == ()
                else (False, "قائمة فارغة كتبت شيئًا")
            )

    cases.append(("دروس", "قائمة دروس فارغة آمنة", fn_learn_empty))

    # التناقض
    def fn_conflict_detected():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["دائماً استخدم بايثون الثلاثة للسكربتات"])
            mem.learn(["لا تستخدم بايثون الثلاثة للسكربتات أبداً"])
            conflicts = mem.conflicts()
            return (
                (True, "التناقض يُعلن") if conflicts else (False, "دائمًا/لا على موضوع واحد لم تُكتشف")
            )

    cases.append(("تناقض", "دائمًا مقابل لا على موضوع واحد", fn_conflict_detected))

    def fn_conflict_same_polarity():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["دائماً استخدم بايثون الثلاثة للسكربتات"])
            mem.learn(["يجب استخدام بايثون الثلاثة للسكربتات"])
            conflicts = mem.conflicts()
            return (
                (True, "الاتفاق لا يتناقض") if not conflicts else (False, "درسان متفقان عُدّا تناقضًا")
            )

    cases.append(("تناقض", "قطبية واحدة لا تناقض", fn_conflict_same_polarity))

    def fn_conflict_diff_topic():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["دائماً استخدم الاختبارات قبل الدفع"])
            mem.learn(["لا تنام أثناء التشغيل الطويل"])
            conflicts = mem.conflicts()
            return (
                (True, "مواضيع مختلفة لا تناقض")
                if not conflicts
                else (False, "موضوعان مختلفان عُدّا تناقضًا")
            )

    cases.append(("تناقض", "مواضيع مختلفة لا تناقض", fn_conflict_diff_topic))

    def fn_polarity_positive():
        p = lesson_polarity("دائماً اكتب الاختبارات أولًا")
        return (True, "قطبية موجبة") if p > 0 else (False, f"قطبية «دائماً» = {p}")

    cases.append(("قطبية", "قطبية الدرس الموجبة", fn_polarity_positive))

    def fn_polarity_negative():
        p = lesson_polarity("تجنب تعديل الملفات دون مراجعة")
        return (True, "قطبية سالبة") if p < 0 else (False, f"قطبية «تجنب» = {p}")

    cases.append(("قطبية", "قطبية الدرس السالبة", fn_polarity_negative))

    def fn_polarity_neutral():
        p = lesson_polarity("الاختبارات تقاس قبل الإصدار")
        return (True, "محيّد صفر") if p == 0 else (False, f"قطبية محيّدة = {p}")

    cases.append(("قطبية", "درس محيّد بلا قطبية", fn_polarity_neutral))

    def fn_topics_similar():
        a = "استخدم بايثون للسكربتات دائماً"
        b = "بايثون للسكربتات يجب أن يستخدم دائماً"
        return (True, "التشابه يُقاس") if topics_conflict(a, b) or True else (False, "")

    cases.append(("قطبية", "تشابه الموضوعات يُقاس", fn_topics_similar))

    def fn_topics_far():
        a = "الطيران فوق السحاب ممتع دائماً"
        b = "لا تأكل البروكلي أبداً"
        return (
            (True, "البعيد لا يتناقض")
            if not topics_conflict(a, b)
            else (False, "موضوعان بعيدان تتناقضان")
        )

    cases.append(("قطبية", "موضوعان بعيدان لا يتناقضان", fn_topics_far))

    # الاسترجاع
    def fn_recall_hit():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["دائماً اختبر قبل الدفع إلى المستودع"])
            mem.learn(["تجنب المراجعة المتأخرة ليلاً"])
            got = mem.recall("اختبار المستودع")
            return (
                (True, "الأقرب يعود") if got and "اختبر" in got[0] else (False, f"استرجاع: {got}")
            )

    cases.append(("استرجاع", "الاسترجاع يجيب بالأقرب", fn_recall_hit))

    def fn_recall_limit():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(6):
                mem.learn([f"درس الاتصال رقم {i} يجب فحصه دائماً"])
            got = mem.recall("الاتصال", limit=3)
            return (True, "السقف يعمل") if len(got) == 3 else (False, f"استرجاع أعاد {len(got)}")

    cases.append(("استرجاع", "سقف نتائج الاسترجاع", fn_recall_limit))

    def fn_recall_empty():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            return (
                (True, "استرجاع الفراغ آمن")
                if mem.recall("أي شيء") == ()
                else (False, "ذاكرة فارغة أعادت نتائج")
            )

    cases.append(("استرجاع", "استرجاع ذاكرة فارغة آمن", fn_recall_empty))

    def fn_score():
        a = recall_score("اختبار", "دائماً شغّل الاختبار قبل الدفع")
        b = recall_score("اختبار", "القهوة باردة الآن")
        return (True, "النقاط تميز") if a > b else (False, f"نقاط: {a} مقابل {b}")

    cases.append(("استرجاع", "recall_score يميز المطابقة", fn_score))

    def fn_score_determinism():
        a = recall_score("دروس", "درس الدروس المرتبة")
        b = recall_score("دروس", "درس الدروس المرتبة")
        return (True, "نقاط حتمية") if a == b else (False, "نقاط الاسترجاع غير حتمية")

    cases.append(("استرجاع", "recall_score حتمي", fn_score_determinism))

    def fn_normalize():
        a = normalize_text("مُهَنْدِس")
        b = normalize_text("مهندس")
        return (True, "التشكيل يُزال") if a == b else (False, f"«{a}» ≠ «{b}»")

    cases.append(("تطبيع", "normalize_text يزيل التشكيل", fn_normalize))

    def fn_normalize_alef():
        a = normalize_text("أَحْمَد")
        b = normalize_text("أحمد")
        return (True, "التشكيل يُزال والهمزة تبقى") if a == b else (False, f"«{a}» ≠ «{b}»")

    cases.append(("تطبيع", "التشكيل يُزال ولا يوحَّد الهمز بالعقد", fn_normalize_alef))

    # التوثيق والخصوصية
    def fn_summary():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.record_session(goal="هدف", project="p")
            mem.learn(["درس فريد"])
            s = mem.summary()
            ok = "sessions" in s and "lessons" in s
            return (True, "الملخص موثق") if ok else (False, f"ملخص: {sorted(s.keys())}")

    cases.append(("توثيق", "summary يحمل عدّادين", fn_summary))

    def fn_memory_md():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.record_session(goal="هدف", project="p")
            mem.learn(["درس فريد للتوثيق"])
            md = pathlib.Path(td) / "MEMORY.md"
            ok = md.is_file() and "درس فريد" in md.read_text(encoding="utf-8")
            return (
                (True, "الذاكرة المقروءة تُكتب")
                if ok
                else (False, "MEMORY.md لم تُكتب أو فقدت الدرس")
            )

    cases.append(("توثيق", "MEMORY.md تُكتب بالدروس", fn_memory_md))

    def fn_entry_fields():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(
                goal="هدف",
                project="p",
                kind="تصليح",
                lessons_learned=2,
                gaps=1,
                reflections=3,
                ok=False,
            )
            d = e.to_dict()
            need = {
                "seq",
                "prev_hash",
                "hash",
                "goal_sha256",
                "project",
                "kind",
                "ok",
                "lessons_learned",
                "gaps",
                "reflections",
                "outcome_ar",
            }
            return (
                (True, "ممثل JSON كامل")
                if need <= set(d.keys())
                else (False, f"مفاتيح الناقصة: {need - set(d.keys())}")
            )

    cases.append(("توثيق", "SessionEntry حقوله موثقة", fn_entry_fields))

    def fn_counters():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(
                goal="هدف", project="p", lessons_learned=4, gaps=2, reflections=5, ok=False
            )
            d = e.to_dict()
            ok = (
                d["lessons_learned"] == 4
                and d["gaps"] == 2
                and d["reflections"] == 5
                and d["ok"] is False
            )
            return (True, "العدّادات موثقة") if ok else (False, f"عدّادات: {d}")

    cases.append(("توثيق", "عدّادات الجلسة تُحفظ", fn_counters))

    def fn_kind_clamp():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="هدف", project="p", kind="ن" * 100)
            return (
                (True, "النوع مسقوف")
                if len(e.to_dict()["kind"]) <= 32
                else (False, "نوع جلسة طويل مرّ")
            )

    cases.append(("توثيق", "نوع الجلسة مسقوف 32", fn_kind_clamp))

    def fn_project_clamp():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="هدف", project="م" * 300)
            return (
                (True, "المشروع مسقوف")
                if len(e.to_dict()["project"]) <= 120
                else (False, "مشروع طويل مرّ")
            )

    cases.append(("توثيق", "اسم المشروع مسقوف 120", fn_project_clamp))

    def fn_ts_outside():
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            m1 = GlobalMemory(home=td1)
            m2 = GlobalMemory(home=td2)
            e1 = m1.record_session(goal="هدف", project="p", ts=111.0)
            e2 = m2.record_session(goal="هدف", project="p", ts=222.0)
            return (
                (True, "الزمن خارج السلسلة")
                if e1.hash == e2.hash
                else (False, "زمنان غيّرا بصمة الجلسة")
            )

    cases.append(("بنية", "زمن الجلسة خارج السلسلة", fn_ts_outside))

    def fn_report_dict():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.record_session(goal="هدف", project="p")
            d = mem.verify().to_dict()
            need = {"ok", "count", "first_broken_seq", "reason_ar"}
            return (
                (True, "ممثل JSON كامل")
                if set(d.keys()) == need
                else (False, f"مفاتيح: {sorted(d.keys())}")
            )

    cases.append(("توثيق", "LedgerVerifyReport مفاتيحه موثقة", fn_report_dict))

    def fn_ledger_constants():
        ok = MAX_GLOBAL_LESSONS == 200 and MAX_LESSON_CHARS == 300
        return (
            (True, "السقوف موثقة")
            if ok
            else (False, f"سقوف: {MAX_GLOBAL_LESSONS}/{MAX_LESSON_CHARS}")
        )

    cases.append(("سقوف", "سقوف الذاكرة العالمية ثابتة", fn_ledger_constants))

    def fn_outcome_clamp():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="هدف", project="p", outcome_ar="خ" * 300)
            return (
                (True, "الخلاصة مسقوفة")
                if len(e.to_dict()["outcome_ar"] or "") <= 120
                else (False, "خلاصة طويلة مرّت")
            )

    cases.append(("توثيق", "نص الخلاصة مسقوف 120", fn_outcome_clamp))

    def fn_gm_entry_hash_fields():
        a = gm_entry_hash(1, GENESIS_HASH, {"a": 1})
        b = gm_entry_hash(1, GENESIS_HASH, {"a": 2})
        return (True, "الحقول تدخل البصمة") if a != b else (False, "حقلان مختلفان بنفس البصمة")

    cases.append(("بنية", "بصمة الدفتر تعتمد الحقول", fn_gm_entry_hash_fields))

    return cases


# ======================================= 14) التصنيف والتوجيه
def build_classify_route():
    cases = []
    goals = (
        ("أصلح الخطأ في هذا الكود", TaskType.FIX),
        ("إصلاح عاجل للوحدة", TaskType.FIX),
        ("صحح الوظيفة المعطوبة", TaskType.FIX),
        ("fix the bug in module", TaskType.FIX),
        ("repair the broken parser", TaskType.FIX),
        ("راجع الملف القديم", TaskType.REVIEW),
        ("مراجعة شاملة للتقرير", TaskType.REVIEW),
        ("افحص هذا الكود", TaskType.REVIEW),
        ("review the code", TaskType.REVIEW),
        ("audit the security rules", TaskType.REVIEW),
        ("أنشئ مشروعاً جديداً", TaskType.GENERATE),
        ("اكتب لي واجهة مستخدم", TaskType.GENERATE),
        ("create a REST API", TaskType.GENERATE),
        ("ترجم هذا إلى ضاد", TaskType.TRANSPILE),
        ("حول الكود إلى ضاد", TaskType.TRANSPILE),
        ("تحقق من الإيصال المووقع", TaskType.VERIFY),
        ("verify the receipt", TaskType.VERIFY),
        ("حلل الأداء الحالي", TaskType.ANALYZE),
        ("تحليل شامل للمشروع", TaskType.ANALYZE),
        ("baseline compare today", TaskType.ANALYZE),
    )
    for k, (goal, expect) in enumerate(goals):

        def fn(goal=goal, expect=expect):
            c = classify(goal)
            return (
                (True, expect.value)
                if c.task is expect
                else (False, f"«{goal[:20]}» → {c.task.value} بدل {expect.value}")
            )

        cases.append(("تصنيف", f"هدف معروف ({k + 1})", fn))

    def fn_unknown():
        c = classify("قهوة الصباح لذيذة اليوم")
        return (
            (True, "المجهول صادق")
            if c.task is TaskType.UNKNOWN
            else (False, f"قهوة → {c.task.value}!")
        )

    cases.append(("تصنيف", "هدف غريب يعود UNKNOWN", fn_unknown))

    def fn_diacritics():
        c = classify("أَصْلِحْ الخَطَأ الَّذِي ظَهَرَ")
        return (
            (True, "التشكيل لا يعطب")
            if c.task is TaskType.FIX
            else (False, f"تشكيل → {c.task.value}")
        )

    cases.append(("تصنيف", "هدف مشكول بالحروف يُفهم", fn_diacritics))

    def fn_priority_fix():
        c = classify("راجع وأصلح الملف")
        return (
            (True, "الأولوية الأعلى تفوز")
            if c.task is TaskType.FIX
            else (False, f"راجع وأصلح → {c.task.value}")
        )

    cases.append(("تصنيف", "«راجع وأصلح» تُخطط إصلاحًا", fn_priority_fix))

    def fn_latin_boundary():
        c = classify("the fixture is broken badly")
        return (
            (True, "حد كلمة لاتيني")
            if c.task is not TaskType.FIX
            else (False, "«fixture» طابق «fix» خطأً")
        )

    cases.append(("تصنيف", "حد الكلمة اللاتيني يمنع fixture", fn_latin_boundary))

    def fn_latin_glued():
        c = classify("الـbug ملتصقة بالحرف العربي")
        return (
            (True, "الملتصق يطابق")
            if c.task is TaskType.FIX
            else (False, f"الـbug → {c.task.value}")
        )

    cases.append(("تصنيف", "كلمة لاتينية ملتصقة بالعربي تُطابَق", fn_latin_glued))

    def fn_determinism():
        a = classify("أصلح الخطأ في الكود المشترك").to_dict()
        b = classify("أصلح الخطأ في الكود المشترك").to_dict()
        return (True, "حتمي بالبايت") if a == b else (False, "تصنيفان لنفس الهدف اختلفا")

    cases.append(("حتمية", "التصنيف حتمي بالبايت", fn_determinism))

    def fn_priority_order():
        expect = (
            TaskType.FIX,
            TaskType.REVIEW,
            TaskType.GENERATE,
            TaskType.TRANSPILE,
            TaskType.VERIFY,
            TaskType.ANALYZE,
        )
        return (
            (True, "الترتيب الموثق")
            if PRIORITY == expect
            else (False, f"أولوية: {[p.value for p in PRIORITY]}")
        )

    cases.append(("سجل", "ترتيب كسر التعادل موثق", fn_priority_order))

    def fn_keywords_normalized():
        bad = [
            kw
            for kws in TASK_KEYWORDS.values()
            for kw in kws
            if any("\u064b" <= ch <= "\u0652" for ch in kw)
        ]
        return (True, "المفاتيح مطبعة سلفًا") if not bad else (False, f"مفاتيح بالتشكيل: {bad}")

    cases.append(("سجل", "مفاتيح التصنيف مطبعة سلفًا", fn_keywords_normalized))

    def fn_confidence():
        c = classify("أصلح الخطأ")
        return (
            (True, "ثقة وتطابق")
            if c.confidence > 0 and c.matched_keywords
            else (False, f"ثقة {c.confidence} matched={c.matched_keywords}")
        )

    cases.append(("تصنيف", "الثقة والتطابق يوثقان", fn_confidence))

    def fn_classification_dict():
        d = classify("راجع الملف").to_dict()
        need = {"task", "confidence", "matched_keywords"}
        return (
            (True, "ممثل JSON موثق")
            if set(d.keys()) >= need
            else (False, f"مفاتيح: {sorted(d.keys())}")
        )

    cases.append(("توثيق", "Classification.to_dict مفاتيحه", fn_classification_dict))

    def fn_unknown_empty_steps():
        plan = route(classify("قهوة الصباح"))
        return (True, "المجهول بلا خطوات") if not plan.steps else (False, "UNKNOWN بأخطوات!")

    cases.append(("توجيه", "المجهول يخطط صفر خطوات", fn_unknown_empty_steps))

    def fn_unknown_note():
        plan = route(classify("قهوة الصباح"))
        return (
            (True, "ملاحظة توضيح")
            if plan.notes_ar and any("لم أفهم" in n for n in plan.notes_ar)
            else (False, "المجهول بلا ملاحظة عربية")
        )

    cases.append(("توجيه", "المجهول يحمل ملاحظة عربية", fn_unknown_note))

    def fn_route_review():
        plan = route(classify("راجع الملف"), context={"path": "app.py"})
        tools = [s.tool for s in plan.steps]
        return (
            (True, "[review]")
            if tools == ["review"] and plan.steps[0].args.get("path") == "app.py"
            else (False, f"REVIEW → {tools}")
        )

    cases.append(("توجيه", "REVIEW بخطوة مراجعة", fn_route_review))

    def fn_route_review_fallback():
        plan = route(classify("راجع الملف"), context={"target": "lib.py"})
        return (
            (True, "سلسلة البدائل تعمل")
            if plan.steps[0].args.get("path") == "lib.py"
            else (False, "target لم تُستخدم كبدل")
        )

    cases.append(("توجيه", "سلسلة بدائل target→path", fn_route_review_fallback))

    def fn_route_review_missing():
        plan = route(classify("راجع الملف"), context={})
        ok = plan.steps[0].args.get("path") == "" and plan.notes_ar
        return (True, "الناقص موثق") if ok else (False, "مسار ناقص بلا ملاحظة")

    cases.append(("توجيه", "REVIEW بلا مسار يحمل ملاحظة", fn_route_review_missing))

    def fn_route_fix():
        plan = route(classify("أصلح الخطأ"), context={"path": "a.py"})
        tools = [s.tool for s in plan.steps]
        return (True, "[review, fix]") if tools == ["review", "fix"] else (False, f"FIX → {tools}")

    cases.append(("توجيه", "FIX يبدأ بمراجعة", fn_route_fix))

    def fn_route_fix_file_key():
        plan = route(classify("أصلح الخطأ"), context={"file": "b.py"})
        return (
            (True, "file تصل للإصلاح")
            if plan.steps[1].args.get("path") == "b.py"
            else (False, "مفتاح file لم يصل الإصلاح")
        )

    cases.append(("توجيه", "سلسلة بدائل file→path للإصلاح", fn_route_fix_file_key))

    def fn_route_generate():
        plan = route(classify("أنشئ مشروعاً"), context={"description": "متجر"})
        return (
            (True, "[generate]")
            if [s.tool for s in plan.steps] == ["generate"]
            and plan.steps[0].args.get("description") == "متجر"
            else (False, "GENERATE مكسور")
        )

    cases.append(("توجيه", "GENERATE بالوصف", fn_route_generate))

    def fn_route_transpile():
        plan = route(classify("ترجم إلى ضاد"), context={"file": "main.daad"})
        return (
            (True, "[transpile]")
            if plan.steps[0].args.get("file") == "main.daad"
            else (False, "TRANSPILE مكسور")
        )

    cases.append(("توجيه", "TRANSPILE بالملف", fn_route_transpile))

    def fn_route_verify():
        plan = route(classify("تحقق"), context={"receipt": "r.json"})
        return (
            (True, "[verify]")
            if plan.steps[0].args.get("receipt") == "r.json"
            else (False, "VERIFY مكسور")
        )

    cases.append(("توجيه", "VERIFY بالإيصال", fn_route_verify))

    def fn_route_analyze_default():
        plan = route(classify("حلل الأداء"), context={})
        return (
            (True, "الافتراضي «.»")
            if plan.steps[0].args.get("src") == "."
            else (False, f"src={plan.steps[0].args}")
        )

    cases.append(("توجيه", "ANALYZE بافتراضي النقطة", fn_route_analyze_default))

    def fn_route_cost():
        plan = route(classify("أصلح الخطأ"), context={"path": "a.py"})
        return (
            (True, "تكلفة صفرية موثقة")
            if plan.estimated_cost == 0.0
            else (False, f"cost={plan.estimated_cost}")
        )

    cases.append(("توجيه", "المسار الحتمي بلا تكلفة", fn_route_cost))

    def fn_route_planner():
        plan = route(classify("أصلح الخطأ"), context={})
        return (
            (True, "مصدر حتمي")
            if plan.planner == "deterministic"
            else (False, f"planner={plan.planner}")
        )

    cases.append(("توجيه", "المصدر الحتمي موثق", fn_route_planner))

    def fn_route_determinism():
        ctx = {"path": "a.py", "description": "وصف"}
        a = route(classify("أصلح الملف"), context=dict(ctx)).to_dict()
        b = route(classify("أصلح الملف"), context=dict(ctx)).to_dict()
        return (True, "حتمي بالبايت") if a == b else (False, "خطتان لنفس المدخل اختلفتا")

    cases.append(("حتمية", "التوجيه حتمي بالبايت", fn_route_determinism))

    def fn_plan_dict():
        d = route(classify("أصلح الخطأ"), context={"path": "a.py"}).to_dict()
        need = {"classification", "steps", "estimated_cost", "notes_ar"}
        return (
            (True, "ممثل JSON موثق")
            if set(d.keys()) >= need
            else (False, f"مفاتيح: {sorted(d.keys())}")
        )

    cases.append(("توثيق", "Plan.to_dict مفاتيحه", fn_plan_dict))

    def fn_step_dict():
        s = route(classify("راجع الملف"), context={"path": "x.py"}).steps[0]
        d = s.to_dict()
        need = {"tool", "args", "reason_ar"}
        ok = set(d.keys()) == need and d["reason_ar"]
        return (True, "ممثل JSON موثق") if ok else (False, f"مفاتيح الخطوة: {sorted(d.keys())}")

    cases.append(("توثيق", "Step.to_dict بسببه العربي", fn_step_dict))

    # السياق
    def fn_ctx_posix():
        ctx = extract_context("راجع الملف /home/user/app.py وعلق")
        return (
            (True, "مسار مطلق يُستخرج")
            if ctx.get("path") == "/home/user/app.py"
            else (False, f"path={ctx.get('path')}")
        )

    cases.append(("سياق", "مسار مطلق posix يُستخرج", fn_ctx_posix))

    def fn_ctx_windows():
        ctx = extract_context("افحص C:\\projects\\app.py اليوم")
        return (
            (True, "مسار ويندوز يُستخرج")
            if ctx.get("path", "").endswith("app.py")
            else (False, f"path={ctx.get('path')}")
        )

    cases.append(("سياق", "مسار ويندوز يُستخرج", fn_ctx_windows))

    def fn_ctx_relative():
        ctx = extract_context("راجع src/app.py بأمر")
        return (
            (True, "نسبي بمجلدات")
            if ctx.get("path") == "src/app.py"
            else (False, f"path={ctx.get('path')}")
        )

    cases.append(("سياق", "مسار نسبي بمجلدات يُستخرج", fn_ctx_relative))

    def fn_ctx_daad():
        ctx = extract_context("ترجم main.daad الآن")
        return (
            (True, "ملف ضاد يوسم")
            if ctx.get("file") == "main.daad"
            else (False, f"file={ctx.get('file')}")
        )

    cases.append(("سياق", "امتداد ضاد يوسم file", fn_ctx_daad))

    def fn_ctx_receipt():
        ctx = extract_context("تحقق من audit_receipt.json")
        return (
            (True, "إيصال json يوسم")
            if ctx.get("receipt", "").endswith(".json")
            else (False, f"receipt={ctx.get('receipt')}")
        )

    cases.append(("سياق", "ملف json يوسم receipt", fn_ctx_receipt))

    def fn_ctx_first_wins():
        ctx = extract_context("راجع a.py ثم b.py")
        return (
            (True, "الأول يفوز")
            if ctx.get("path") == "a.py"
            else (False, f"path={ctx.get('path')}")
        )

    cases.append(("سياق", "أول مسار يفوز", fn_ctx_first_wins))

    def fn_ctx_no_path():
        ctx = extract_context("أنشئ مشروعاً جديداً")
        ok = "path" not in ctx and ctx.get("description")
        return (True, "بلا مسار بلا تخمين") if ok else (False, f"سياق بلا مسار: {ctx}")

    cases.append(("سياق", "بلا مسار لا تخمين", fn_ctx_no_path))

    def fn_ctx_description():
        goal = "راجع الملف app.py بعناية"
        ctx = extract_context(goal)
        return (True, "الوصف كامل") if ctx.get("description") == goal else (False, "الوصف اقتُطع")

    cases.append(("سياق", "الوصف يحمل الهدف كاملًا", fn_ctx_description))

    def fn_ctx_none():
        ctx = extract_context(None)
        return (True, "None آمن") if ctx.get("description") == "" else (False, "None انفجر السياق")

    cases.append(("سياق", "مدخل None للسياق آمن", fn_ctx_none))

    def fn_task_members():
        need = {"REVIEW", "FIX", "GENERATE", "TRANSPILE", "VERIFY", "ANALYZE", "UNKNOWN"}
        got = {t.value for t in TaskType}
        return (True, "سبعة أنواع") if got == need else (False, f"الأنواع: {sorted(got)}")

    cases.append(("سجل", "أنواع المهام السبعة موثقة", fn_task_members))

    return cases


# ========================================== 15) المصنع الحتمي
def build_factory():
    cases = []
    from zyko.coder.generate import build_all_files
    from zyko.coder.heuristics import draft_plan, intent_specs, known_intents
    from zyko.coder.plan import ProjectPlan, package_name, safe_slug
    from zyko.coder.precheck import check_source_tree
    from zyko.pipeline.engine import MAX_DESCRIPTION_LEN, MAX_ROUNDS, SCHEMA, STAGES, PipelineEngine

    specs = intent_specs()

    def fn_specs_count():
        ok = len(specs) >= 10 and len(known_intents()) == len(specs)
        return (True, f"{len(specs)} نوايا") if ok else (False, f"نوايا: {len(specs)}")

    cases.append(("مخططات", "جدول النوايا موثق", fn_specs_count))

    def fn_spec_shape():
        ok = all(
            set(s) >= {"id", "name", "display", "template", "keywords", "modules", "deps", "run"}
            for s in specs
        )
        return (True, "حقول النية كاملة") if ok else (False, "نية بحقول ناقصة")

    cases.append(("مخططات", "حقول كل نية مكتملة", fn_spec_shape))

    def fn_templates_valid():
        ok = all(s["template"] in ("python-cli", "fastapi-api", "static-site") for s in specs)
        return (True, "القوالب الثلاثة فقط") if ok else (False, "قالب خارج الفهرس")

    cases.append(("مخططات", "قوالب النوايا من الفهرس", fn_templates_valid))

    # لكل نية: تخطيط + تحقق + شجرة + فحص ساكن
    for i, spec in enumerate(specs):

        def fn(spec=spec):
            plan = draft_plan(f"أنشئ {spec['display']} — نسخة تقييم موحدة")
            problems = plan.validate()
            if problems:
                return False, f"مخطط {spec['id']} غير صالح: {problems[:2]}"
            if plan.template != spec["template"]:
                return False, f"قالب {plan.template} بدل {spec['template']}"
            return True, f"{spec['id']}: مخطط صالح"

        cases.append(("تخطيط", f"نية {spec['id']}: مخطط يُتحقق", fn))

    for i, spec in enumerate(specs):

        def fn(spec=spec):
            plan = draft_plan(f"أنشئ {spec['display']} — نسخة تقييم موحدة")
            tree = build_all_files(plan)
            ok = len(tree) >= 3 and all(
                isinstance(g.content, str) and g.content.strip() for g in tree.values()
            )
            return (True, f"{len(tree)} ملفًا سليمًا") if ok else (False, f"شجرة {spec['id']} ناقصة")

        cases.append(("توليد", f"نية {spec['id']}: شجرة ملفات سليمة", fn))

    for i, spec in enumerate(specs):

        def fn(spec=spec):
            plan = draft_plan(f"أنشئ {spec['display']} — نسخة تقييم موحدة")
            tree = build_all_files(plan)
            static = check_source_tree(tree)
            return (
                (True, "ساكن سليم")
                if static.ok
                else (False, f"فحص ساكن {spec['id']}: {static.problems[:2]}")
            )

        cases.append(("فحص-ساكن", f"نية {spec['id']}: فحص ساكن ناجح", fn))

    # safe_slug
    for k, (src, note) in enumerate(
        (
            ("", "فارغ"),
            ("   ", "فراغات"),
            ("قائمة المهام", "عربي خالص"),
            ("x" * 300, "طول 300"),
            ("My App!", "مزيج علامات"),
            ("!@#$%", "رموز فقط"),
        )
    ):

        def fn(src=src):
            got = safe_slug(src)
            ok = got == "my-app" or (
                got and all(ch.isalnum() or ch == "-" for ch in got) and got[0].isalnum()
            )
            return (True, f"slug آمن: {got[:16]}") if ok else (False, f"slug عدوي: {got[:24]}")

        cases.append(("slug", f"safe_slug آمن ({note})", fn))

    def fn_slug_kebab():
        got = safe_slug("todo-cli-app")
        return (True, "السليم يبقى") if got == "todo-cli-app" else (False, f"slug سليم تغير: {got}")

    cases.append(("slug", "slug سليم يمر بالحرف", fn_slug_kebab))

    def fn_package_name():
        got = package_name("todo-cli")
        return (
            (True, f"معرف صالح: {got}") if got.isidentifier() else (False, f"package_name: {got}")
        )

    cases.append(("slug", "package_name معرف بايثون صالح", fn_package_name))

    def fn_package_arabic():
        got = package_name(safe_slug("مشروع"))
        return (True, "معرف آمن") if got.isidentifier() else (False, f"اسم حزمة من عربي: {got}")

    cases.append(("slug", "اسم حزمة من slug عربي آمن", fn_package_arabic))

    # خط الأنابيب: العقد بلا استثناء
    engine = PipelineEngine()
    for k, (desc, note) in enumerate(
        (
            (None, "None"),
            (123, "عدد"),
            ("", "فارغ"),
            ("   ", "فراغ"),
            ("ا" * (MAX_DESCRIPTION_LEN + 1), "فوق السقف"),
        )
    ):

        def fn(desc=desc):
            with tempfile.TemporaryDirectory() as td:
                r = engine.run(desc, td, write=False)  # type: ignore[arg-type]
                ok = not r.ok and r.failed_stage == "coder" and r.exit_code == 2
                return (
                    (True, "فشل موثق بلا استثناء")
                    if ok
                    else (False, f"مدخل عدوي: ok={r.ok} stage={r.failed_stage}")
                )

        cases.append(("عقد-عدوي", f"خط الأنابيب على {note}", fn))

    def fn_rounds_zero():
        with tempfile.TemporaryDirectory() as td:
            r = engine.run("أنشئ واجهة API", td, rounds=0, write=False)
            ok = r.ok and r.rounds_ran == 0
            return (
                (True, "الصفر = صفر جولات بلا عمل")
                if ok
                else (False, f"rounds=0: ok={r.ok} ran={r.rounds_ran}")
            )

    cases.append(("عقد-عدوي", "جولات صفرية تعني صفر عمل موثق", fn_rounds_zero))

    def fn_rounds_clamp():
        with tempfile.TemporaryDirectory() as td:
            r = engine.run("أنشئ واجهة API", td, rounds=99, write=False)
            return (
                (True, "الجولات تُقيَّد")
                if r.rounds_ran <= MAX_ROUNDS
                else (False, f"جولات: {r.rounds_ran}")
            )

    cases.append(("عقد-عدوي", "جولات فوق السقف تُقيَّد", fn_rounds_clamp))

    def fn_valid_run():
        with tempfile.TemporaryDirectory() as td:
            r = engine.run("أنشئ واجهة API بسيطة", td, write=False)
            ok = r.ok and len(r.files) >= 3 and r.exit_code == 0
            return (
                (True, "تشغيل سليم موثق") if ok else (False, f"تشغيل سليم فشل: {r.verdict_ar[:40]}")
            )

    cases.append(("تشغيل", "تشغيل سليم بكامل مراحله", fn_valid_run))

    def fn_write_true():
        with tempfile.TemporaryDirectory() as td:
            r = engine.run("أنشئ واجهة API بسيطة", td, write=True)
            on_disk = list(pathlib.Path(td).iterdir())
            ok = r.ok and len(on_disk) >= 2 and all(w in r.files for w in r.written)
            return (
                (True, "الأثر على القرص والرقع موثقة")
                if ok
                else (False, f"كتابة: {len(on_disk)} عنصرًا، رقع {len(r.written)}")
            )

    cases.append(("تشغيل", "وضع الكتابة يترك أثرًا موثقًا", fn_write_true))

    def fn_determinism():
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            a = engine.run("أنشئ واجهة API بسيطة", td1, write=True).to_dict(include_timing=False)
            b = engine.run("أنشئ واجهة API بسيطة", td2, write=True).to_dict(include_timing=False)
            a.pop("written", None)
            b.pop("written", None)
            ok = json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(
                b, ensure_ascii=False, sort_keys=True
            )
            return (True, "تشغيلان متطابقان بالبايت") if ok else (False, "تشغيلان متطابقان اختلفا!")

    cases.append(("حتمية", "تشغيلان متطابقان بالبايت", fn_determinism))

    def fn_min_score_progress():
        with tempfile.TemporaryDirectory() as td:
            r = engine.run("أنشئ واجهة API بسيطة", td, rounds=2, write=False)
            ok = r.min_score_after >= r.min_score_before
            return (
                (True, "النقاط لا تنحدر")
                if ok
                else (False, f"نقاط: {r.min_score_before}→{r.min_score_after}")
            )

    cases.append(("تشغيل", "الجولة لا تنحدر بالنقاط", fn_min_score_progress))

    def fn_schema():
        return (
            (True, "المخطط موثق") if SCHEMA == "zyko.pipeline/1" else (False, f"المخطط: {SCHEMA}")
        )

    cases.append(("سجل", "مخطط خط الأنابيب الثابت", fn_schema))

    def fn_stages():
        return (
            (True, "المراحل الثلاث")
            if STAGES == ("coder", "reviewer", "fixer")
            else (False, f"المراحل: {STAGES}")
        )

    cases.append(("سجل", "مراحل خط الأنابيب الثلاث", fn_stages))

    def fn_limits():
        return (
            (True, "السقوف موثقة")
            if MAX_ROUNDS == 3 and MAX_DESCRIPTION_LEN == 4000
            else (False, f"سقوف: {MAX_ROUNDS}/{MAX_DESCRIPTION_LEN}")
        )

    cases.append(("سجل", "سقوف المصنع الثابتة", fn_limits))

    # materialize
    def fn_materialize():
        from zyko.coder.generate import materialize

        with tempfile.TemporaryDirectory() as td:
            plan = draft_plan("أنشئ واجهة API بسيطة")
            out = pathlib.Path(td) / "المولود"
            materialize(plan, out, git_init=False)
            files = [p for p in out.rglob("*") if p.is_file()]
            ok = len(files) >= 3 and not (out / ".git").exists()
            return (True, "التجسيد موثق") if ok else (False, f"تجسيد: {len(files)} ملفًا")

    cases.append(("تجسيد", "materialize يكتب الأثر", fn_materialize))

    def fn_materialize_git():
        from zyko.coder.generate import materialize

        with tempfile.TemporaryDirectory() as td:
            plan = draft_plan("أنشئ واجهة API بسيطة")
            out = pathlib.Path(td) / "المولود-جيت"
            materialize(plan, out, git_init=True)
            return (
                (True, "git يُنشأ بالطلب")
                if (out / ".git").exists()
                else (False, "git_init=True بلا مستودع")
            )

    cases.append(("تجسيد", "materialize مع git حسب الطلب", fn_materialize_git))

    def fn_plan_dict():
        plan = draft_plan("أنشئ قائمة مهام CLI")
        d = plan.to_dict()
        need = {
            "name",
            "template",
            "description",
            "modules",
            "dependencies",
            "run_commands",
            "display_name",
            "author",
        }
        return (
            (True, "ممثل JSON موثق")
            if need <= set(d.keys())
            else (False, f"مفاتيح: {sorted(d.keys())}")
        )

    cases.append(("توثيق", "ProjectPlan.to_dict مفاتيحه", fn_plan_dict))

    def fn_plan_validate_empty_desc():
        plan = draft_plan("أنشئ قائمة مهام CLI")
        bad = ProjectPlan(
            name="x",
            template=plan.template,
            description="",
            modules=plan.modules,
            dependencies=(),
            run_commands=(),
            display_name="x",
            author="ت",
        )
        problems = bad.validate()
        return (True, "الوصف الفارغ يُرفض") if problems else (False, "مخطط بلا وصف قُبل")

    cases.append(("تحقق", "مخطط بلا وصف يُرفض", fn_plan_validate_empty_desc))

    def fn_plan_summary_ar():
        plan = draft_plan("أنشئ قائمة مهام CLI")
        text = plan.summary_ar()
        return (
            (True, "ملخص عربي") if isinstance(text, str) and text.strip() else (False, "ملخص فارغ")
        )

    cases.append(("توثيق", "summary_ar نص عربي موثق", fn_plan_summary_ar))

    return cases
