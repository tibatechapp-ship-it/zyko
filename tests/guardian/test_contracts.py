"""اختبارات عقود المحرّس — الأنواع والبروتوكولات والبصمة الحتمية."""

from __future__ import annotations

import re
from typing import get_args, get_type_hints

from zyko.guardian import Decision, GateResult, Guardian
from zyko.guardian.contracts import compute_fingerprint
from zyko.guardian.core import DefaultGuardian

# ------------------------------------------------------------ أنواع القرار


def test_decision_fields_roundtrip():
    d = Decision(
        verdict="ALLOW",
        gate_results=[],
        fingerprint="a" * 64,
        reason_ar="مقبول: اجتاز جميع البوابات",
    )
    assert d.verdict == "ALLOW"
    assert d.fingerprint == "a" * 64
    assert d.reason_ar == "مقبول: اجتاز جميع البوابات"
    assert d.gate_results == []


def test_gate_result_fields_roundtrip():
    g = GateResult(
        gate_name="PIIGate",
        passed=False,
        reason_ar="اكتُشف PII: هاتف ×1",
        details={"counts": {"phone": 1}},
    )
    assert g.gate_name == "PIIGate"
    assert g.passed is False
    assert g.reason_ar == "اكتُشف PII: هاتف ×1"
    assert g.details == {"counts": {"phone": 1}}


def test_decision_verdict_literal_is_exact_triple():
    hint = get_type_hints(Decision)["verdict"]
    assert get_args(hint) == ("ALLOW", "DENY", "REVIEW")


# ------------------------------------------------------------ البصمة الحتمية


def test_fingerprint_is_deterministic_sha256_hex():
    results = [GateResult("PIIGate", True, "لا بيانات شخصية مكتشفة", {})]
    fp1 = compute_fingerprint("كود نظيف", results)
    fp2 = compute_fingerprint("كود نظيف", results)
    assert fp1 == fp2
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)
    # اقتراح مختلف → بصمة مختلفة
    assert fp1 != compute_fingerprint("كود مختلف", results)
    # نتيجة بوابة مختلفة → بصمة مختلفة
    changed = [GateResult("PIIGate", False, "اكتُشف PII: هاتف ×1", {})]
    assert fp1 != compute_fingerprint("كود نظيف", changed)


# ------------------------------------------------------------ بروتوكول المحرّس


def test_guardian_protocol_is_runtime_checkable():
    assert isinstance(DefaultGuardian(), Guardian)

    class NotGuardian:
        pass

    assert not isinstance(NotGuardian(), Guardian)
