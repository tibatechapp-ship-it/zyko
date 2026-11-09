"""اختبارات النموذج الوهمي — الحتمية والسيناريوهات والعقد."""

from __future__ import annotations

import pytest

from zyko.guardian import PIIGate
from zyko.mock_llm import MockLLM

# ------------------------------------------------------------ العقد الأساسي


def test_health_returns_true():
    assert MockLLM("clean").health() is True
    assert MockLLM().health() is True


def test_default_scenario_is_clean():
    assert MockLLM().scenario == "clean"


def test_unknown_scenario_raises_arabic_error():
    with pytest.raises(ValueError, match="سيناريو غير معروف"):
        MockLLM("لا_يوجد")


# ------------------------------------------------------------ propose الحتمية


async def test_clean_propose_returns_nonempty_string():
    p = await MockLLM("clean").propose("أضف دالة")
    assert isinstance(p, str)
    assert len(p) > 0
    assert "مرحباً" in p


async def test_clean_propose_is_deterministic():
    llm = MockLLM("clean")
    p1 = await llm.propose("أضف دالة")
    p2 = await llm.propose("أضف دالة")
    assert p1 == p2


async def test_clean_propose_free_of_pii():
    p = await MockLLM("clean").propose("أضف دالة")
    r = await PIIGate().check(p)
    assert r.passed is True


async def test_suspicious_propose_contains_phone():
    llm = MockLLM("suspicious")
    p = await llm.propose("أضف دالة")
    assert "+9665" in p
    assert "اتصل" in p
    assert llm.calls == 1


async def test_hostile_propose_contains_pii_and_bidi_override():
    p = await MockLLM("hostile").propose("أضف دالة")
    assert "+9665" in p
    assert "\u202e" in p


async def test_propose_with_context_kwarg_unchanged():
    llm = MockLLM("clean")
    base = await llm.propose("طلبي")
    with_ctx = await llm.propose("طلبي", context={"session": "s1"})
    assert with_ctx == base
    assert llm.calls == 2


async def test_scenario_proposals_are_pairwise_distinct():
    prompts = "نفس الطلب بالضبط"
    proposals = [await MockLLM(s).propose(prompts) for s in ("clean", "suspicious", "hostile")]
    assert len(set(proposals)) == 3
