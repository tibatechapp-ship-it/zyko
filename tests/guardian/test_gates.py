"""اختبارات البوابات الثلاث — الخصوصية ثم الاتجاه ثم البنية."""

from __future__ import annotations

from zyko.guardian.gates import PIIGate, RTLGate, StructuralGate

# ------------------------------------------------------------ بوابة الخصوصية


async def test_pii_gate_passes_clean_code():
    r = await PIIGate().check('def greet(name):\n    return "مرحباً يا " + name')
    assert r.gate_name == "PIIGate"
    assert r.passed is True


async def test_pii_gate_rejects_phone():
    r = await PIIGate().check("اتصل بـ +966501234567")
    assert r.passed is False
    assert "هاتف" in r.reason_ar
    assert r.details["counts"]["phone"] == 1
    # القيم المكتشفة نفسها لا تُسرد في التفاصيل — العدّ فقط
    assert all(not isinstance(v, str) for v in r.details.values())


async def test_pii_gate_rejects_iban():
    r = await PIIGate().check("IBAN: SA0380000000608010167519")
    assert r.passed is False
    assert "آيبان" in r.reason_ar
    assert r.details["counts"]["iban"] == 1


# ------------------------------------------------------------ بوابة الاتجاه


async def test_rtl_gate_passes_clean_arabic():
    r = await RTLGate().check("هذا نص عربي سليم بلا محارف خفية")
    assert r.gate_name == "RTLGate"
    assert r.passed is True
    assert r.details["hidden_count"] == 0


async def test_rtl_gate_rejects_bidi_override():
    # محرف RLO يُبنى بتسلسل هروب لا محرفًا خامًا في المصدر
    r = await RTLGate().check("نص سليم" + "\u202e" + "ومحرف خفي")
    assert r.passed is False
    assert r.details["hidden_count"] == 1
    assert "اتجاه" in r.reason_ar


# ------------------------------------------------------------ بوابة البنية


async def test_structural_gate_rejects_empty_or_blank():
    for blank in ("", "   \n  "):
        r = await StructuralGate().check(blank)
        assert r.passed is False
        assert "فارغ" in r.reason_ar


async def test_structural_gate_rejects_control_chars():
    r = await StructuralGate().check("كود\x00خبيث")
    assert r.passed is False
    assert "تحكم" in r.reason_ar
    assert r.details["control_chars"] == 1
