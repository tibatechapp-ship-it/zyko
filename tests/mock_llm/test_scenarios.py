"""اختبارات سيناريوهات النموذج الوهمي — سجل محدود حصريًا وقوالب تحقق بواقع المحرس."""

from __future__ import annotations

from zyko.guardian import PIIGate, RTLGate, StructuralGate
from zyko.mock_llm import SCENARIOS, MockLLM

# ------------------------------------------------------------ السجل


def test_registry_has_exactly_three_scenarios():
    assert set(SCENARIOS) == {"clean", "suspicious", "hostile"}


def test_scenario_metadata_complete():
    for name in ("clean", "suspicious", "hostile"):
        s = SCENARIOS[name]
        assert s.name == name
        assert len(s.name_ar) > 0
        assert len(s.description_ar) > 0
        assert len(s.template) > 0


# ------------------------------------------------------------ القوالب بواقع المحرس


async def test_clean_template_passes_all_gates():
    p = SCENARIOS["clean"].render("أضف دالة")
    assert (await PIIGate().check(p)).passed is True
    assert (await RTLGate().check(p)).passed is True
    assert (await StructuralGate().check(p)).passed is True


async def test_suspicious_template_fails_pii_only():
    p = SCENARIOS["suspicious"].render("أضف دالة")
    assert (await PIIGate().check(p)).passed is False
    assert (await RTLGate().check(p)).passed is True
    assert (await StructuralGate().check(p)).passed is True


async def test_hostile_template_fails_pii_and_rtl():
    p = SCENARIOS["hostile"].render("أضف دالة")
    assert (await PIIGate().check(p)).passed is False
    assert (await RTLGate().check(p)).passed is False


async def test_hostile_template_passes_structural():
    p = SCENARIOS["hostile"].render("أضف دالة")
    assert (await StructuralGate().check(p)).passed is True


# ------------------------------------------------------------ الحتمية والدمج


async def test_render_is_deterministic():
    s = SCENARIOS["clean"]
    assert s.render("س") == s.render("س")
    assert MockLLM("clean")._scenario() is s


async def test_render_embeds_prompt_and_leaves_no_token():
    s = SCENARIOS["clean"]
    p = s.render("ارسم لي زهرة")
    assert "ارسم لي زهرة" in p
    assert "{prompt}" not in p
