"""اختبارات الحاكم الشكلي — «المُقترح يبحث، والحاكم يحكم».

العقود المستهدفة:
  * الحكم حتمي بالبايت: نفس المصدر يعطي نفس التقرير.
  * لا تنفيذ للمقترح أبداً — الفحص سكوني خالص بـast.
  * التوجيهات الثلاثة: صياغة سليمة تُقبل، المشوّه يُرفض بالدليل.
  * الأسماء الخارجية والسمات مرفوضة؛ المسموح القياسي مقفول.
  * مجال عاقر/ناقص = تعذّر تحقق لا قبول فارغ.
  * بوابة FormalGate اختيارية صريحة: بلا عقود تمر بتصريح.
"""

from __future__ import annotations

from zyko.tools.formal.engine import (
    VerdictKind,
    check_source,
    evidence_lines,
    summarize,
)

GOOD_SOURCE = """\
# zyko:requires: x >= 0
# zyko:ensures: result * 2 == x
# zyko:domain: x = range(0, 8)
def double(x):
    return x * 2
"""

NO_CONTRACT_SOURCE = """\
def plain(x):
    return x + 1
"""


# ------------------------------------------------------------ الحكم الأساسي


def test_source_with_valid_contracts_is_accepted():
    report = check_source(GOOD_SOURCE)
    assert report.verdict is VerdictKind.ACCEPT
    assert report.functions_with_contracts == 1
    assert report.directives_checked == 3


def test_determinism_same_source_same_report():
    first = summarize(check_source(GOOD_SOURCE))
    second = summarize(check_source(GOOD_SOURCE))
    assert first == second


def test_unparseable_proposal_is_rejected_loudly():
    report = check_source("def broken(:\n    pass")
    assert report.verdict is VerdictKind.REJECT
    assert "لا يُجمَّع" in report.findings[0].reason_ar


def test_no_contracts_is_accept_with_explicit_declaration():
    report = check_source(NO_CONTRACT_SOURCE)
    assert report.verdict is VerdictKind.ACCEPT
    assert report.functions_with_contracts == 0
    assert report.details["no_contracts"] is True
    assert "اختياري صريح" in report.findings[0].reason_ar


# ------------------------------------------------------------ صياغة التوجيهات


def test_malformed_directive_expression_is_rejected():
    source = "# zyko:ensures: result ==\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "صياغة غير صالحة" in report.findings[0].reason_ar


def test_attribute_access_in_contract_is_rejected():
    source = "# zyko:ensures: result.real >= 0\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "سمات الكائنات" in report.findings[0].reason_ar


def test_non_allowlisted_call_in_contract_is_rejected():
    source = "# zyko:ensures: open('f') is None\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "مقصورة على المسموح" in report.findings[0].reason_ar


def test_allowlisted_builtin_is_accepted():
    source = (
        "# zyko:ensures: abs(result) <= 100\n"
        "# zyko:domain: x = [-5, -2, 2]\n"
        "def f(x):\n    return x\n"
    )
    report = check_source(source)
    assert report.verdict is VerdictKind.ACCEPT


# ------------------------------------------------------------ النطاق والأسماء


def test_names_outside_params_are_rejected():
    source = "# zyko:ensures: result == secret\n# zyko:domain: x = [1]\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "خارج المعاملات" in report.findings[0].reason_ar


def test_result_as_parameter_is_rejected():
    source = "# zyko:ensures: result >= 0\ndef f(result):\n    return result\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "محجوز للناتج" in report.findings[0].reason_ar


def test_domain_for_unknown_param_is_rejected():
    source = (
        "# zyko:ensures: result >= 0\n# zyko:domain: y = range(0, 3)\ndef f(x):\n    return x\n"
    )
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "ليست معاملاً" in report.findings[0].reason_ar


def test_bad_domain_shape_is_rejected():
    source = "# zyko:ensures: result >= 0\n# zyko:domain: x = range(0)\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.REJECT
    assert "شكل المجال غير مسموح" in report.findings[0].reason_ar


# ------------------------------------------------------------ تعذّر التحقق


def test_missing_domain_is_unknown_never_accept():
    source = "# zyko:ensures: x >= 0\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.UNKNOWN
    assert "تعذّر التحقق السكوني" in report.findings[0].reason_ar


def test_contract_without_ensures_is_unknown():
    source = "# zyko:requires: x >= 0\n# zyko:domain: x = [1, 2]\ndef f(x):\n    return x\n"
    report = check_source(source)
    assert report.verdict is VerdictKind.UNKNOWN
    assert "لا شيء يُثبت" in report.findings[0].reason_ar


# ------------------------------------------------------------ الأدلة والملخص


def test_evidence_lines_carry_directive_and_line():
    source = "# zyko:ensures: result == secret\ndef f(x):\n    return x\n"
    lines = evidence_lines(check_source(source))
    assert lines
    assert "secret" in lines[0]
    assert "سطر 1" in lines[0]


def test_summary_is_receipt_ready():
    summary = summarize(check_source(GOOD_SOURCE))
    assert summary == {
        "verdict": "accept",
        "functions_with_contracts": 1,
        "directives_checked": 3,
        "rejects": 0,
        "unknowns": 0,
    }


# ------------------------------------------------------------ بوابة المحرّس


async def test_formal_gate_passes_clean_code_with_declaration():
    from zyko.guardian.gates import FormalGate

    result = await FormalGate().check(NO_CONTRACT_SOURCE)
    assert result.gate_name == "FormalGate"
    assert result.passed is True
    assert "اختياري صريح" in result.reason_ar
    assert result.details["no_contracts"] is True


async def test_formal_gate_passes_valid_contracts():
    from zyko.guardian.gates import FormalGate

    result = await FormalGate().check(GOOD_SOURCE)
    assert result.passed is True
    assert result.details["functions_with_contracts"] == 1


async def test_formal_gate_rejects_broken_contract():
    from zyko.guardian.gates import FormalGate

    result = await FormalGate().check("# zyko:ensures: result == secret\ndef f(x):\n    return x\n")
    assert result.passed is False
    assert "لا يحققها" in result.reason_ar


async def test_formal_gate_unknown_marks_review_without_denial():
    from zyko.guardian.gates import FormalGate

    result = await FormalGate().check("# zyko:ensures: x >= 0\ndef f(x):\n    return x\n")
    assert result.passed is True  # تعذّر التحقق لا يرفض — يحال للمراجعة
    assert result.details["review_recommended"] is True


async def test_default_gates_stay_three_and_formal_is_opt_in():
    from zyko.guardian.gates import default_gates

    names = [getattr(g, "gate_name", type(g).__name__) for g in default_gates()]
    assert names == ["PIIGate", "RTLGate", "StructuralGate"]
