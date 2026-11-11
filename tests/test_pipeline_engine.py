"""اختبارات محرك حلقة التغذية الراجعة: التكامل، الجولات، ومصائر الملاحظات.

العقد المُختبر هنا:
- وصف عربي سليم ⇒ مشروع كامل مُراجَع ومُصلَح (بلا شبكة وبلا نموذج)
- كل ملاحظة في النتيجة تحمل suggestion_ar عربيًا غير فارغ
- لا ملف يتراجع درجته، والمُصلِح على الناتج النهائي لا يغيّر شيئًا
- الجولات: 0 = مراجعة دون إصلاح، >السقف = تقييد بملاحظة عربية
"""

from __future__ import annotations

import ast

import pytest

from zyko.coder.plan import PlanValidationError, ProjectPlan
from zyko.fixer import FixerEngine
from zyko.fixer.edits import Edit
from zyko.fixer.fixes import FixContext
from zyko.pipeline.engine import (
    MAX_ROUNDS,
    SCHEMA,
    STAGE_CODER,
    VERDICT_NO_PY,
    PipelineEngine,
    PipelineResult,
)
from zyko.reviewer.engine import ReviewEngine
from zyko.reviewer.rules import Finding

DESC_TODO = "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها"
DESC_BLOG = "مدونة عربية أنشر فيها مقالاتي مع صفحة تعريف عني"
DESC_API = "واجهة برمجية لحجوزات عيادة أسنان: المريض يختار الخدمة والموعد"


@pytest.fixture(scope="module")
def engine():
    return PipelineEngine()


class _InjectedReviewer(ReviewEngine):
    """مراجع يضيف ملاحظات مدفونة فوق المراجعة الحقيقية — مصائر الملاحظات حتميًا."""

    def __init__(self, extras: dict[str, list[Finding]]) -> None:
        super().__init__()
        self._extras = extras

    def review_source(self, source: str, filename: str = "<text>"):
        result = super().review_source(source, filename)
        for key, findings in self._extras.items():
            if key in filename:
                result.findings.extend(findings)
        return result


_FINDING_FIXABLE = Finding(
    rule_id="R-QLT-204",
    severity="low",
    category="quality",
    line=1,
    col=0,
    message_ar="رمز عام بلا docstring (حقن اختباري)",
    suggestion_ar="أضف docstring عربيًا يشرح الغرض",
)
_FINDING_MANUAL = Finding(
    rule_id="R-QLT-201",
    severity="medium",
    category="quality",
    line=1,
    col=0,
    message_ar="دالة أطول من الحد المسموح (حقن اختباري)",
    suggestion_ar="قسّمها إلى دوال أصغر بمسؤولية واحدة",
)


def _probe_planner(ctx: FixContext) -> list[Edit]:  # noqa: ARG001
    """مخطط حقن حتمي: تعليق واحد أعلى الملف — يثبت أنّ المُصلِح يكتب فعلًا."""
    return [
        Edit(
            line=1,
            col=0,
            end_line=1,
            end_col=0,
            replacement="# حقن اختباري حتمي: المُصلِح فعّال\n",
            rule_id="R-QLT-204",
            note_ar="حقن اختباري",
        )
    ]


# ------------------------------------------------------------ التكامل
def test_end_to_end_generates_reviews_and_fixes(engine, tmp_path):
    r = engine.run(DESC_TODO, tmp_path / "todo", write=True)
    assert r.ok is True
    assert r.failed_stage is None
    assert r.plan is not None and r.plan["name"] == "todo-cli"
    assert r.files and r.py_files
    assert r.rounds_ran == 1
    # القوالب المثالية تخرج 100/100 بلا أي ملاحظة — لا إصلاح مطلوب؛
    # قيمة حلقة مراجعة←إصلاح تُثبَت في بوابة المرحلة 4 بمعيب مقصود حتمي،
    # وتدفق الملاحظات نفسه يُختبر أدناه بمراجع محقون.
    assert r.fixed_total == r.manual_total == r.open_total == 0
    assert r.min_score_before == r.min_score_after == 100
    assert r.verdict_ar
    assert r.exit_code == 0


def test_written_files_parse_and_differ_from_raw(engine, tmp_path):
    out = tmp_path / "todo"
    r = engine.run(DESC_TODO, out, write=True)
    assert r.ok
    # كل ملف بايثون على القرص يُحلل
    for rel in r.py_files:
        ast.parse((out / rel).read_text(encoding="utf-8"))
    # الملفات المعدّلة على القرص تطابق final_sources
    for rel in r.written:
        assert (out / rel).read_text(encoding="utf-8") == r.final_sources[rel]
    assert len(r.written) == r.changed_files


def test_dry_run_touches_no_disk(engine, tmp_path):
    out = tmp_path / "never"
    r = engine.run(DESC_TODO, out, write=False)
    assert r.ok and r.files
    assert not out.exists()
    assert r.written == []
    assert r.final_sources  # النصوص النهائية متاحة في الذاكرة


def test_three_templates_complete(engine, tmp_path):
    for i, desc in enumerate((DESC_TODO, DESC_BLOG, DESC_API)):
        r = engine.run(desc, tmp_path / f"t{i}", write=False)
        assert r.ok, f"{desc}: {r.error_ar}"
        assert r.py_files, "لكل قالب ملفات بايثون للمراجعة"
        for f in r.per_file:
            assert f["score_after"] >= f["score_before"]


def test_blog_template_minimal_python(engine, tmp_path):
    """قالب الموقع الساكن يمر رغم قلة ملفاته — بلا انهيار وبلا ادعاء زائف."""
    r = engine.run(DESC_BLOG, tmp_path / "blog", write=False)
    assert r.ok
    assert any(p.endswith(".py") for p in r.py_files)
    assert r.verdict_ar not in ("", VERDICT_NO_PY)


# --------------------------------------------------- مصائر الملاحظات
def test_every_outcome_carries_suggestion_ar(tmp_path):
    """كل ملاحظة (حتى المحقونة حتميًا) تحمل حقولها العربية كاملة."""
    reviewer = _InjectedReviewer({"cli.py": [_FINDING_FIXABLE]})
    r = PipelineEngine(reviewer=reviewer).run(DESC_TODO, tmp_path / "todo", write=False)
    assert r.ok
    total = 0
    for f in r.per_file:
        for o in f["outcomes"]:
            total += 1
            assert o["suggestion_ar"], f"{f['path']}/{o['rule_id']}: suggestion_ar فارغ"
            assert o["message_ar"]
            assert o["status"] in ("fixed", "manual", "open")
            assert o["status_ar"]
            assert o["action_ar"]
    assert total > 0
    assert r.fixed_total + r.manual_total + r.open_total == total


def test_fixed_rules_disappear_from_after(engine, tmp_path):
    r = engine.run(DESC_TODO, tmp_path / "todo", write=False)
    assert r.ok
    for f in r.per_file:
        fixed_rules = {o["rule_id"] for o in f["outcomes"] if o["status"] == "fixed"}
        # نتحقق من الاتساق: إذا صُرح بإصلاح قاعدة كليًا فهي تختفي من «يبقى»
        open_rules = {o["rule_id"] for o in f["outcomes"] if o["status"] == "open"}
        assert not (fixed_rules & open_rules), f"قاعدة في حالتين معًا: {fixed_rules & open_rules}"


def test_manual_findings_keep_manual_status(tmp_path):
    """الملاحظة اليدوية (غير القابلة للإصلاح الآلي) تحتفظ بحالتها وسببها."""
    reviewer = _InjectedReviewer({"core.py": [_FINDING_MANUAL]})
    r = PipelineEngine(reviewer=reviewer).run(DESC_TODO, tmp_path / "todo", write=False)
    assert r.ok
    assert r.manual_total >= 1
    for f in r.per_file:
        for o in f["outcomes"]:
            if o["status"] == "manual":
                assert o["action_ar"], "كل ملاحظة يدوية تحمل سبب بقاءها بالعربية"


# ------------------------------------------------------------ الجولات
def test_rounds_zero_reviews_without_fixing(engine, tmp_path):
    r = engine.run(DESC_TODO, tmp_path / "todo", rounds=0, write=False)
    assert r.ok
    assert r.rounds_ran == 0
    assert r.fixed_total == 0
    assert r.changed_files == 0
    for f in r.per_file:
        for o in f["outcomes"]:
            if o["status"] == "open":
                assert "جولات=0" in o["action_ar"]


def test_rounds_above_cap_clamped_with_note(engine, tmp_path):
    r = engine.run(DESC_TODO, tmp_path / "todo", rounds=50, write=False)
    assert r.ok
    assert r.rounds_requested == 50
    assert r.rounds_ran <= MAX_ROUNDS
    assert any("السقف" in n for n in r.notes)


def test_extra_rounds_converge_to_same_result(engine, tmp_path):
    """جولة إضافية على ناتج متقارب لا تضيف تغييرًا — التقارب مضمون."""
    r1 = engine.run(DESC_TODO, tmp_path / "a", rounds=1, write=False)
    r3 = engine.run(DESC_TODO, tmp_path / "b", rounds=MAX_ROUNDS, write=False)
    assert r1.ok and r3.ok
    assert r3.final_sources == r1.final_sources


def test_idempotence_on_final_sources(engine, tmp_path):
    r = engine.run(DESC_API, tmp_path / "api", write=False)
    assert r.ok
    fixer = FixerEngine()
    for rel, src in r.final_sources.items():
        again = fixer.fix_source(src, rel)
        assert not again.changed, f"الاعتدال مكسور في {rel}"


# -------------------------------------------------------- الأحكام والخروج
def test_exit_code_contract(engine, tmp_path):
    r = engine.run(DESC_TODO, tmp_path / "todo", write=False)
    assert r.ok
    if r.min_score_after >= 90:
        assert r.exit_code == 0
    else:
        assert r.exit_code == 1


def test_to_dict_schema_and_determinism(engine, tmp_path):
    a = engine.run(DESC_TODO, tmp_path / "a", write=False)
    b = engine.run(DESC_TODO, tmp_path / "b", write=False)
    da, db = a.to_dict(), b.to_dict()
    assert da["schema"] == SCHEMA
    assert da == db, "نفس الوصف ⇒ نفس القاموس كاملًا"
    assert "seconds" not in da
    assert "seconds" in a.to_dict(include_timing=True)
    assert "final_sources" not in da  # نصوص التشغيل لا تدخل الحمولة


def test_description_trimmed_in_result(engine, tmp_path):
    r = engine.run(f"  {DESC_TODO}  \n", tmp_path / "todo", write=False)
    assert r.ok
    assert r.description == DESC_TODO


# ---------------------------------------------------- حقن الأعطال (coder)
def _broken_plan(_desc: str) -> ProjectPlan:
    return ProjectPlan(name="", template="", description="", modules=())


def _raising_plan(_desc: str) -> ProjectPlan:
    raise RuntimeError("planner exploded")


def test_invalid_plan_from_injected_planner(engine, tmp_path):
    bad = PipelineEngine(planner=_broken_plan)
    r = bad.run(DESC_TODO, tmp_path / "x", write=False)
    assert r.ok is False
    assert r.failed_stage == STAGE_CODER
    assert r.exit_code == 2
    assert r.problems, "رفض المخطط يحمل المشاكل بالعربية"
    assert any("الاسم" in p for p in r.problems)


def test_crashing_planner_becomes_structured_failure(engine, tmp_path):
    bad = PipelineEngine(planner=_raising_plan)
    r = bad.run(DESC_TODO, tmp_path / "x", write=False)
    assert r.ok is False
    assert r.failed_stage == STAGE_CODER
    assert r.exit_code == 2
    assert "RuntimeError" in (r.error_ar or "")


def test_plan_validation_error_class_is_preserved(engine, tmp_path):
    def rejecting(_desc: str) -> ProjectPlan:
        raise PlanValidationError(["مشكلة تجريبية أولى", "مشكلة تجريبية ثانية"])

    bad = PipelineEngine(planner=rejecting)
    r = bad.run(DESC_TODO, tmp_path / "x", write=False)
    assert r.ok is False
    assert r.problems == ["مشكلة تجريبية أولى", "مشكلة تجريبية ثانية"]


def test_pipeline_result_defaults():
    """النتيجة الافتراضية الفارغة آمنة للتسلسل: الحكم فارغ ⇒ خروج 1 ميكانيكيًا."""
    r = PipelineResult(description="")
    assert r.ok is True
    assert r.exit_code == 1
    assert r.to_dict()["schema"] == SCHEMA
    assert r.final_sources == {}
