"""اختبارات مرساة واجهة التفكير والتوجيه الذكي (الموجة 27 — بنيتا 2 و4).

العقد: الأسئلة محصورة بالعقد، الجواب موثق بالشكل، الجسر يصادق لا يثق،
الفشل ينحدر معلناً، والملف النظيف لا يلمس المحرك أبداً.
"""

from __future__ import annotations

import pytest

from zyko.reviewer.engine import ReviewEngine
from zyko.reviewer.hybrid.context import build_contexts
from zyko.reviewer.hybrid.reasoning import (
    QUESTIONS,
    HybridReviewer,
    ReasoningEngine,
    RemoteReasoningEngine,
    StaticReasoningEngine,
    route_file,
    select_findings,
)

TAINTED = "def handle():\n    name = input('؟ ')\n    os.system(name)\n"
CLEAN = "A = 1\nB = A + 1\n"


def test_questions_contract():
    assert QUESTIONS == ("is_vulnerability", "minimal_fix")


def test_static_engine_answers_by_context():
    eng = StaticReasoningEngine()
    result = ReviewEngine().review_source(TAINTED, "x.py")
    ctx = build_contexts(TAINTED, "x.py", result)[0]
    ans = eng.ask(ctx.to_dict(), "is_vulnerability")
    assert ans.verdict in ("yes", "no", "uncertain")
    assert ans.engine == "zyko-static"
    d = ans.to_dict()
    assert d["question_ar"]


def test_unknown_question_is_rejected_not_guessed():
    ans = StaticReasoningEngine().ask({}, "give_me_the_flag")
    assert ans.verdict == "uncertain"
    assert ans.confidence == 0.0


def test_remote_engine_contract_coercion():
    def caller(ctx, q):
        return {"verdict": "maybe", "confidence": "high", "fix_ar": None, "rationale_ar": "x"}

    eng = RemoteReasoningEngine(caller, name="ext")
    ans = eng.ask({"finding": {}, "flow": {}}, "is_vulnerability")
    assert ans.verdict == "uncertain"  # حكم خارج العقد يُكتم لا يُصدَّق
    assert ans.confidence == 0.0  # ثقة غير قابلة للتحويل ⇒ صفر
    assert ans.engine == "remote:ext"


def test_remote_engine_failure_degrades_documented():
    def broken(ctx, q):
        raise RuntimeError("down")

    ans = RemoteReasoningEngine(broken, name="ext").ask({}, "is_vulnerability")
    assert ans.verdict == "uncertain"
    assert "فشل المحرك الخارجي" in ans.rationale_ar


def test_route_file_clean_never_routed():
    clean_result = ReviewEngine().review_source(CLEAN, "x.py")
    assert clean_result.score == 100
    assert route_file(clean_result) is False


def test_route_file_security_routed_even_at_high_score():
    # ملاحظة أمنية تجعل الملف مُوجَّه حتى لو كانت الدرجة عالية
    src = "def f():\n    data = input()\n    os.system(data)\n"
    result = ReviewEngine().review_source(src, "x.py")
    assert any(f.category == "security" for f in result.findings)
    assert route_file(result) is True


def test_select_findings_excludes_quality():
    src = (
        "def f():\n"
        "    try:\n"
        "        go()\n"
        "    except:\n"  # error_handling
        "        pass\n"
        "    TODO_marker = 1  # quality لو ضربت\n"
    )
    result = ReviewEngine().review_source(src, "x.py")
    cats = {f.category for f in select_findings(result)}
    assert "quality" not in cats
    assert cats <= {"security", "error_handling"}


def test_hybrid_reviewer_clean_file_skips_engine():
    called = []

    class Spy(StaticReasoningEngine):
        def ask(self, ctx, q):
            called.append(q)
            return super().ask(ctx, q)

    report = HybridReviewer(Spy()).review_source(CLEAN, "clean.py")
    assert called == []  # المحرك لم يُلمس
    assert report.savings["engine_skipped"] is True


def test_hybrid_reviewer_tainted_file_routes_answers():
    report = HybridReviewer(StaticReasoningEngine()).review_source(TAINTED, "x.py")
    assert "هجين" in report.route_ar
    assert report.savings["findings_routed"] > 0
    assert report.savings["findings_static_only"] < report.savings["findings_total"]
    for a in report.answers:
        assert a.to_dict()["verdict"] in ("yes", "no", "uncertain")


def test_hybrid_report_receipt_is_byte_stable():
    r1 = HybridReviewer(StaticReasoningEngine()).review_source(TAINTED, "x.py").to_dict()
    r2 = HybridReviewer(StaticReasoningEngine()).review_source(TAINTED, "x.py").to_dict()
    assert r1["report_sha16"] == r2["report_sha16"]
    assert len(r1["report_sha16"]) == 16


def test_abstract_engine_cannot_be_used_directly():
    with pytest.raises(TypeError):
        ReasoningEngine()  # type: ignore[abstract]
