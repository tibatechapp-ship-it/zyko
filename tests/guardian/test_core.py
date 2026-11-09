"""اختبارات المحرّس الافتراضي — القرار والترتيب المقدّس والبصمة وحالة المراجعة."""

from __future__ import annotations

from zyko.guardian import DefaultGuardian

CLEAN = "def greet(name):\n    return name"
PHONE = "اتصل بـ +966501234567"

# ------------------------------------------------------------ القرار الأساسي


async def test_allow_on_clean_proposal():
    d = await DefaultGuardian().check(CLEAN)
    assert d.verdict == "ALLOW"
    assert all(g.passed for g in d.gate_results)
    assert d.reason_ar.startswith("مقبول")
    assert len(d.fingerprint) == 64


async def test_deny_on_phone_proposal():
    d = await DefaultGuardian().check(PHONE)
    assert d.verdict == "DENY"
    assert "PII" in d.reason_ar or "هاتف" in d.reason_ar
    assert d.gate_results[0].passed is False


# ------------------------------------------------------------ الترتيب المقدّس (R7)


async def test_gate_order_is_fixed_piis_rtl_structural():
    d = await DefaultGuardian().check(CLEAN)
    assert [g.gate_name for g in d.gate_results] == [
        "PIIGate",
        "RTLGate",
        "StructuralGate",
    ]


async def test_all_gates_run_even_after_first_failure():
    d = await DefaultGuardian().check(PHONE)
    assert [g.gate_name for g in d.gate_results] == [
        "PIIGate",
        "RTLGate",
        "StructuralGate",
    ]
    assert d.gate_results[0].gate_name == "PIIGate"
    assert d.gate_results[0].passed is False
    # الهاتف لا يفسد الاتجاه ولا البنية — البوابتان التاليتان تجتازان
    assert d.gate_results[1].passed is True
    assert d.gate_results[2].passed is True


# ------------------------------------------------------------ البصمة الحتمية


async def test_fingerprint_deterministic_across_calls():
    g = DefaultGuardian()
    d1 = await g.check(CLEAN)
    d2 = await g.check(CLEAN)
    assert d1.fingerprint == d2.fingerprint
    assert len(d1.fingerprint) == 64


async def test_fingerprint_varies_by_proposal():
    g = DefaultGuardian()
    d1 = await g.check("اقتراح الأول")
    d2 = await g.check("اقتراح الثاني")
    assert d1.fingerprint != d2.fingerprint


# ------------------------------------------------------------ حالة المراجعة والحدود


async def test_review_on_gate_error_is_safe_state():
    class ExplodingGate:
        gate_name = "ExplodingGate"

        async def check(self, proposal: str):
            raise RuntimeError("عطل مقصود للاختبار")

    d = await DefaultGuardian(gates=[ExplodingGate()]).check(CLEAN)
    assert d.verdict == "REVIEW"
    assert "مراجعة" in d.reason_ar
    assert d.gate_results[0].passed is False
    assert d.gate_results[0].details["error_type"] == "RuntimeError"


async def test_deny_on_oversized_proposal():
    d = await DefaultGuardian().check("x" * 100_001)
    assert d.verdict == "DENY"
    structural = d.gate_results[2]
    assert structural.gate_name == "StructuralGate"
    assert structural.passed is False
    assert "الحد الأقصى" in structural.reason_ar
