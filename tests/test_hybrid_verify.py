"""اختبارات مرساة التحقق الذاتي (الموجة 27 — بنية 3).

العقد: إصلاح المحرك لا يُصدَّق — البوابة الثابتة تعيد تشغيل القواعد
وتحكم بأربعة فحوص، والرفض بأسباب عربية مسماة، والحتمية بالبايت.
"""

from __future__ import annotations

import json

from zyko.reviewer.hybrid.verify import FixVerifier

ORIGINAL = (
    "def handle():\n"
    "    name = input('؟ ')\n"
    "    try:\n"
    "        go(name)\n"
    "    except:\n"          # ERR-BAREEXC-001 — الإصلاح المقصود هنا
    "        pass\n"
    "    return name\n"
)

GOOD_FIX = ORIGINAL.replace("    except:\n", "    except (ValueError, TypeError):\n")


def test_good_fix_accepted():
    v = FixVerifier().verify(ORIGINAL, GOOD_FIX, filename="x.py", target_rule_id="R-ERR-001")
    assert v.accepted is True
    assert v.checks == {
        "parses": True,
        "no_new_findings": True,
        "score_not_worse": True,
        "target_addressed": True,
    }
    assert v.reasons_ar == ()


def test_fix_that_breaks_syntax_rejected():
    v = FixVerifier().verify(ORIGINAL, "def broken(:\n", target_rule_id="R-ERR-001")
    assert v.accepted is False
    assert v.checks["parses"] is False
    assert any("لا يُحلَّل" in r for r in v.reasons_ar)


def test_fix_introducing_new_finding_rejected():
    # الإصلاح يعالج except العاري لكنه يضيف eval جديد — ملاحظة لم تكن في الأصل
    bad_fix = GOOD_FIX.replace("    return name\n", "    return eval(name)\n")
    v = FixVerifier().verify(ORIGINAL, bad_fix, target_rule_id="R-ERR-001")
    assert v.accepted is False
    assert v.checks["no_new_findings"] is False
    assert any("ملاحظات جديدة" in r for r in v.reasons_ar)


def test_fix_that_ignores_target_rejected():
    v = FixVerifier().verify(ORIGINAL, ORIGINAL, target_rule_id="R-ERR-001")
    assert v.accepted is False
    assert v.checks["target_addressed"] is False
    assert any("لم تنقص" in r for r in v.reasons_ar)


def test_partial_fix_count_decrease_accepted():
    # الأصل يحمل استثناءين عاريين، الإصلاح يعالج واحداً — العدّ ينقص فتقبل
    src = "def f():\n    try:\n        a()\n    except:\n        pass\n    try:\n        b()\n    except:\n        pass\n"
    fixed = src.replace("    except:\n        pass\n    try:\n        b()", "    except (ValueError,):\n        pass\n    try:\n        b()", 1)
    v = FixVerifier().verify(src, fixed, target_rule_id="R-ERR-001")
    assert v.accepted is True
    assert v.score_after >= v.score_before


def test_no_target_means_addressed_trivially():
    v = FixVerifier().verify(ORIGINAL, GOOD_FIX)
    assert v.checks["target_addressed"] is True
    assert v.accepted is True


def test_verdict_byte_determinism():
    v1 = FixVerifier().verify(ORIGINAL, GOOD_FIX, target_rule_id="R-ERR-001").to_dict()
    v2 = FixVerifier().verify(ORIGINAL, GOOD_FIX, target_rule_id="R-ERR-001").to_dict()
    assert json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True)
    assert len(v1["fixed_sha16"]) == 16


def test_verdict_schema_and_scores():
    d = FixVerifier().verify(ORIGINAL, GOOD_FIX, target_rule_id="R-ERR-001").to_dict()
    assert d["schema"] == "zyko.hybrid.fix_verdict/1"
    assert d["score_after"] >= d["score_before"]
