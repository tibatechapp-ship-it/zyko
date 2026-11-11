"""اختبارات متانة الحلقة: مدخلات عدائية ⇒ فشل مهيكل عربي، لا استثناءات.

العقد التعاقدي نفسه الذي تحمّله المراجع والمُصلِح في المرحلتين 2 و3:
أي مدخل معادٍ يُنتج نتيجة موقعة (failed_stage + سبب عربي + خروج 2)،
وأي عطب داخلي في مخطِّط/مراجع/مُصلِح محقون يُصدَر مهيكلاً بلا انهيار،
والحتمية تبقى بايتية حتى تحت الضغط.
"""

from __future__ import annotations

import json

import pytest

from tests.test_pipeline_engine import _FINDING_FIXABLE, _InjectedReviewer, _probe_planner
from zyko.fixer import FixerEngine
from zyko.pipeline.engine import (
    MAX_DESCRIPTION_LEN,
    STAGE_CODER,
    STAGE_FIXER,
    STAGE_PIPELINE,
    STAGE_REVIEWER,
    PipelineEngine,
)

DESC = "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها"


@pytest.fixture(scope="module")
def engine():
    return PipelineEngine()


def assert_structured_failure(r, stage=None):
    assert r.ok is False
    assert r.exit_code == 2
    assert r.error_ar, "كل فشل مهيكل يحمل سببه بالعربية"
    assert r.verdict_ar.startswith("فشل")
    if stage is not None:
        assert r.failed_stage == stage


# ------------------------------------------------------ مدخلات الوصف
@pytest.mark.parametrize(
    "bad_description",
    ["", "   ", "\n\t  \n", "ص", None, 42, 3.14, [], {}, object(), "ا" * 5000],
)
def test_hostile_descriptions_never_raise(engine, tmp_path, bad_description):
    r = engine.run(bad_description, tmp_path / "x", write=False)
    assert_structured_failure(r, STAGE_CODER)
    # الحد المعلن يُطبق بالرسالة
    if isinstance(bad_description, str) and len(bad_description.strip()) > MAX_DESCRIPTION_LEN:
        assert "طويل جدًا" in r.error_ar


def test_control_characters_description_is_safe(engine, tmp_path):
    """محارف التحكم لا تُسقط الحلقة — إما رفض أو تشغيل سليم بلا استثناء."""
    r = engine.run("\x00\x01\x02 قائمة مهام", tmp_path / "x", write=False)
    assert r.ok in (True, False)  # لا استثناء من أي نوع
    if r.ok:
        assert r.py_files


def test_emoji_only_description_is_safe(engine, tmp_path):
    r = engine.run("😀😀😀 😀😀", tmp_path / "x", write=False)
    assert r.ok in (True, False)
    if r.ok:
        assert r.description == "😀😀😀 😀😀"


def test_rtl_marks_and_tashkeel_description(engine, tmp_path):
    """التشكيل والتطويل لا يكسران المخطط — نية افتراضية آمنة."""
    r = engine.run("قَائِمَة ـمـهـام لِلفريق", tmp_path / "x", write=False)
    assert r.ok, r.error_ar
    assert r.plan["template"] in ("python-cli", "fastapi-api", "static-site")


# ------------------------------------------------------- مدخلات الجولات
@pytest.mark.parametrize("bad_rounds", [-1, -99, "كثيرة", 1.5, True, False, None])
def test_hostile_rounds_never_raise(engine, tmp_path, bad_rounds):
    r = engine.run(DESC, tmp_path / "x", rounds=bad_rounds, write=False)
    assert_structured_failure(r, STAGE_PIPELINE)


# --------------------------------------------------------- مدخل المجلد
def test_file_as_out_dir_is_structured_failure(engine, tmp_path):
    target = tmp_path / "ملف-عادي.txt"
    target.write_text("أنا ملف لا مجلد", encoding="utf-8")
    r = engine.run(DESC, target, write=True)
    assert_structured_failure(r, STAGE_CODER)


def test_non_empty_dir_is_structured_failure(engine, tmp_path):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "قائم.txt").write_text("عمل المستخدم لا يُمسّ", encoding="utf-8")
    r = engine.run(DESC, occupied, write=True)
    assert_structured_failure(r, STAGE_CODER)
    assert "غير فارغ" in r.error_ar
    assert (occupied / "قائم.txt").read_text(encoding="utf-8") == "عمل المستخدم لا يُمسّ"


def test_unwritable_fixed_output_is_structured(engine, tmp_path, monkeypatch):
    """عطب قرص أثناء كتابة النسخ المُصلَحة ⇒ فشل مهيكل لا انهيار.

    نُفشل الكتابة **فوق ملف قائم** فقط — وهي بالضبط خطوة كتابة الإصلاحات
    (التوليد يكتب ملفات جديدة، فلا يتأثر) — عزل دقيق للخطوة المستهدفة.
    القوالب المثالية لا تنتج إصلاحات، فتُحقن ملاحظة قابلة للإصلاح حتميًا
    في cli.py لتفعيل خطوة الكتابة نفسها.
    """
    real_write_text = __import__("pathlib").Path.write_text

    def failing_overwrite(self, data, *a, **k):
        if self.suffix == ".py" and self.exists():
            raise OSError("disk full (simulated)")
        return real_write_text(self, data, *a, **k)

    monkeypatch.setattr("pathlib.Path.write_text", failing_overwrite)
    fixer = FixerEngine(
        reviewer=_InjectedReviewer({"cli.py": [_FINDING_FIXABLE]}),
        planners={"R-QLT-204": _probe_planner},
    )
    r = PipelineEngine(fixer=fixer).run(DESC, tmp_path / "todo", write=True)
    monkeypatch.undo()
    assert_structured_failure(r, STAGE_FIXER)
    assert "النسخ المُصلَحة" in r.error_ar


# ------------------------------------------------- حقن أعطال المراحل
class ExplodingReviewer:
    """مراجع معطوب: ينهار عند أول مراجعة — يجب تصديره مهيكلاً."""

    def review_source(self, source, filename="<text>"):  # noqa: ARG002
        raise ValueError("reviewer exploded")

    def review_file(self, path):
        raise ValueError("reviewer exploded")


class ExplodingFixer:
    """مصلح معطوب: ينهار عند أول إصلاح."""

    def fix_source(self, source, filename="<text>"):  # noqa: ARG002
        raise RuntimeError("fixer exploded")


def test_crashing_reviewer_is_structured(engine, tmp_path):
    bad = PipelineEngine(reviewer=ExplodingReviewer())
    r = bad.run(DESC, tmp_path / "x", write=False)
    assert_structured_failure(r, STAGE_REVIEWER)
    assert "ValueError" in r.error_ar


def test_crashing_fixer_is_structured(engine, tmp_path):
    bad = PipelineEngine(fixer=ExplodingFixer())
    r = bad.run(DESC, tmp_path / "x", write=False)
    assert_structured_failure(r, STAGE_FIXER)
    assert "RuntimeError" in r.error_ar


# ------------------------------------------------ الحتمية تحت الضغط
def test_failure_results_are_deterministic(engine, tmp_path):
    a = engine.run("", tmp_path / "a", write=False)
    b = engine.run("", tmp_path / "b", write=False)
    assert a.to_dict() == b.to_dict()


def test_failure_json_is_loadable_and_complete(engine, tmp_path):
    r = engine.run(None, tmp_path / "x", write=False)
    d = json.loads(json.dumps(r.to_dict(), ensure_ascii=False))
    assert d["ok"] is False
    assert d["failed_stage"] == STAGE_CODER
    assert d["plan"] is None and d["files"] == []


def test_success_after_failures_untouched(engine, tmp_path):
    """سلسلة مدخلات عدائية لا تفسد التشغيل السليم بعدها (بلا حالة خفية)."""
    for bad in ("", None, 42):
        assert engine.run(bad, tmp_path / "bad", write=False).ok is False
    r = engine.run(DESC, tmp_path / "good", write=False)
    assert r.ok
    assert r.fixed_total == 0  # القوالب المثالية: لا ملاحظات ولا إصلاحات
