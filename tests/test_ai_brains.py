"""اختبارات عقول طبقة الذكاء (المرحلة 8): كل اقتراح يمرّ بوابة قبل قبوله."""

from __future__ import annotations

import pytest

from zyko.ai.brains import (
    Brain,
    GateVerdict,
    GatedBrain,
    PlannerBrain,
    Proposal,
    check_proposal_gates,
)

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"
PII_GOAL = "قائمة مهام — للتنسيق اتصل على 0501234567"


# ------------------------------------------------------------- بوابات الاقتراح
def test_clean_text_passes_both_gates_in_order() -> None:
    verdicts = check_proposal_gates(CLEAN_GOAL)
    assert [v.gate for v in verdicts] == ["pii", "rtl"]  # الترتيب ثابت دائمًا
    assert all(v.passed for v in verdicts)


def test_pii_rejects_hard_and_skips_rtl() -> None:
    verdicts = check_proposal_gates(PII_GOAL)
    pii, rtl = verdicts
    assert pii.gate == "pii" and not pii.passed
    assert "phone" in pii.details_ar
    assert rtl.gate == "rtl" and not rtl.passed  # لم يُفحص — رفض سابق
    assert "لم يُفحص" in rtl.details_ar


def test_arabic_indic_phone_also_rejected() -> None:
    verdicts = check_proposal_gates("مشروع تواصل — جوال ٠٥٠١٢٣٤٥٦٧")
    assert not verdicts[0].passed


def test_empty_text_has_no_verdicts_so_not_accepted() -> None:
    proposal = Proposal(text="   ", brain="x", deterministic=True, verdicts=())
    assert not proposal.accepted


# ------------------------------------------------------------- العقل الحتمي
def test_planner_brain_is_deterministic_and_accepted_for_clean_goal() -> None:
    brain = PlannerBrain()
    assert brain.deterministic is True
    proposal = brain.propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.brain == "planner"
    assert proposal.text.strip()  # ملخص المخطط الحتمي


def test_planner_brain_proposal_is_byte_deterministic() -> None:
    a = PlannerBrain().propose(CLEAN_GOAL)
    b = PlannerBrain().propose(CLEAN_GOAL)
    assert a.text == b.text
    assert a.verdicts == b.verdicts


def test_planner_brain_pii_goal_rejected_at_pii_gate() -> None:
    proposal = PlannerBrain().propose(PII_GOAL)
    assert not proposal.accepted
    pii = next(v for v in proposal.verdicts if v.gate == "pii")
    assert not pii.passed


def test_planner_brain_never_leaks_exceptions() -> None:
    """مدخل عدوي (كائن غريب) ⇒ خطة احتياطية حتمية موثّقة، لا استثناء."""
    proposal = PlannerBrain().propose(object())  # type: ignore[arg-type]
    assert proposal.brain == "planner"
    assert proposal.text.strip()  # خطة احتياطية بدل الانهيار
    assert all(v.passed for v in proposal.verdicts)


# ------------------------------------------------------------- الغلاف المقيّد
class _LooseBrain:
    """عقل اختبار بلا بوابات — الغلاف فرضها عليه."""

    name = "loose"
    deterministic = False

    def propose(self, request: str) -> Proposal:
        return Proposal(text=str(request), brain=self.name, deterministic=self.deterministic)


class _ExplodingBrain:
    name = "boom"
    deterministic = False

    def propose(self, request: str) -> Proposal:
        raise RuntimeError("انفجار تجريبي")


def test_gated_brain_forces_factory_gates_on_any_brain() -> None:
    gated = GatedBrain(_LooseBrain())
    clean = gated.propose(CLEAN_GOAL)
    assert clean.accepted
    assert clean.brain == "gated:loose"
    dirty = gated.propose(PII_GOAL)
    assert not dirty.accepted  # نص العقل الخام لا يتجاوز البوابة أبدًا


def test_gated_brain_preserves_determinism_flag() -> None:
    assert GatedBrain(_LooseBrain()).deterministic is False
    assert GatedBrain(PlannerBrain()).deterministic is True


def test_gated_brain_captures_brain_crash_as_rejection() -> None:
    gated = GatedBrain(_ExplodingBrain())
    proposal = gated.propose("أي هدف")
    assert not proposal.accepted
    brain = next(v for v in proposal.verdicts if v.gate == "brain")
    assert not brain.passed
    assert "RuntimeError" in brain.details_ar


def test_brain_protocol_is_runtime_checkable() -> None:
    assert isinstance(PlannerBrain(), Brain)  # type: ignore[arg-type]


def test_gate_verdict_defaults() -> None:
    v = GateVerdict(gate="pii", passed=True)
    assert v.details_ar == ""
