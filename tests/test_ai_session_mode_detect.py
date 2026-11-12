"""اختبارات اكتشاف نمط الجلسة آليًا (جولة 10) — وعلة حية وجدها التدقيق.

العلة الحية: حرس مجلد الإخراج كان يمنع **كل** مجلد غير فارغ في وضع
الكتابة قبل توزيع النمط — فجلسة النمط القائم (`existing`) لا تستطيع
العمل على أي مشروع حقيقي أبداً (كل مشروع غير فارغ). والنمط نفسه كان
يتطلب علماً صريحاً دائماً: هدف «راجع وأصلح ملفاً قائماً» بلا علم صريح
كان يذهب للمصنع.

العقود الجديدة:
1. الكشف حتمي: مسار موجود في الهدف ⇒ existing، وإلا factory — بسببه العربي في الإيصال.
2. العلم الصريح يغلب الكشف دائماً.
3. النمط القائم في وضع الكتابة يعمل على مجلد مشروع غير فارغ (انحلال العلة).
4. حرس مجلد الإخراج يظل عقد المصنع باقيًا كاملاً.
"""

from __future__ import annotations

from pathlib import Path

from zyko.ai.session import AISession, detect_session_mode

from tests.test_ai_session_existing import SICK_CODE, GOAL_FIX


def _make_file(tmp_path: Path, name: str = "sample.py") -> Path:
    target = tmp_path / name
    target.write_text(SICK_CODE, encoding="utf-8")
    return target


# --------------------------------------------------------------- الكشف الحتمي
def test_detect_existing_when_goal_names_real_file(tmp_path):
    target = _make_file(tmp_path)
    mode, reason = detect_session_mode(f"راجع وأصلح {target} بدقة", tmp_path)
    assert mode == "existing"
    assert "قائماً" in reason and str(target) in reason


def test_detect_factory_when_goal_has_no_path():
    mode, reason = detect_session_mode("أنشئ مشروع قائمة مهام عربي", "/tmp/whatever")
    assert mode == "factory"
    assert "لا يحدد ملفاً" in reason


def test_detect_factory_when_path_missing(tmp_path):
    mode, reason = detect_session_mode("راجع وأصلح src/غير_موجود.py", tmp_path)
    assert mode == "factory"
    assert "غير موجود" in reason


def test_detect_is_deterministic(tmp_path):
    target = _make_file(tmp_path)
    goal = f"راجع وأصلح {target}"
    assert detect_session_mode(goal, tmp_path) == detect_session_mode(goal, tmp_path)


# --------------------------------------------------------------- العلة الحية
def test_live_bug_regression_existing_write_on_nonempty_project(tmp_path):
    """العلة الحية: جلسة قائمة بوضع الكتابة على مشروع غير فارغ — كانت محجوبة."""
    target = _make_file(tmp_path)
    project = tmp_path / "real-project"
    project.mkdir()
    (project / "README.md").write_text("# مشروع حقيقي غير فارغ\n", encoding="utf-8")
    session = AISession(mode="existing", fail_under=0)
    receipt = session.run(f"راجع وأصلح {target}", project, write=True)
    mode_step = next(s for s in receipt.steps if s.step == "mode")
    assert mode_step.ok
    orch = next(s for s in receipt.steps if s.step == "orchestrator")
    assert orch.ok


def test_auto_mode_picks_existing_without_explicit_scientia(tmp_path):
    """بلا علم صريح: هدف على ملف قائم ⇒ existing تلقائياً وقرار موثق."""
    target = _make_file(tmp_path)
    receipt = AISession(fail_under=0).run(f"راجع وأصلح {target}", tmp_path / "out", write=False)
    mode_step = next(s for s in receipt.steps if s.step == "mode")
    assert mode_step.ok and "existing" in mode_step.details_ar
    assert any(s.step == "orchestrator" for s in receipt.steps)


def test_auto_mode_picks_factory_for_generation_goal(tmp_path):
    receipt = AISession().run("أنشئ مشروع مفكرة عربية", tmp_path / "gen", write=False)
    mode_step = next(s for s in receipt.steps if s.step == "mode")
    assert mode_step.ok and "factory" in mode_step.details_ar


def test_explicit_mode_overrides_detection(tmp_path):
    """العلم الصريح يغلب الكشف — هدف على ملف قائم مع نمط factory صريح."""
    target = _make_file(tmp_path)
    session = AISession(mode="factory")
    receipt = session.run(f"راجع وأصلح {target}", tmp_path / "gen", write=False)
    mode_step = next(s for s in receipt.steps if s.step == "mode")
    assert "صريح" in mode_step.details_ar and "factory" in mode_step.details_ar
    # المصنع فعلاً: لا بوابة orchestrator القائمة
    assert not any(s.step == "orchestrator" for s in receipt.steps)


def test_factory_out_dir_guard_stays_enforced(tmp_path):
    """حرس مجلد الإخراج عقد المصنع باقيًا: مجلد غير فارغ + نمط مصنع ⇒ رفض."""
    out = tmp_path / "occupied"
    out.mkdir()
    (out / "something.txt").write_text("مشغول\n", encoding="utf-8")
    receipt = AISession(mode="factory").run("أنشئ مشروع مفكرة", out, write=True)
    assert not receipt.ok and receipt.failed_step == "out"
    assert "موجود وغير فارغ" in receipt.steps[-1].details_ar


def test_invalid_explicit_mode_still_raises():
    import pytest

    with pytest.raises(ValueError):
        AISession(mode="nope")
