"""بوابة قبول المرحلة 1 (D20–21): 10 أوصاف عربية — توليد 10/10 ونجاح ≥8/10."""

from __future__ import annotations

from zyko.coder.gate import (
    DESCRIPTIONS,
    GATE_MIN_PASSED,
    GateResult,
    run_acceptance_gate,
)
from zyko.coder.heuristics import draft_plan, known_intents


def test_gate_descriptions_are_ten_realistic_arabic() -> None:
    assert len(DESCRIPTIONS) == 10
    for d in DESCRIPTIONS:
        assert len(d) >= 15
        # عربية فعلًا — تحتوي حروفًا عربية
        assert any("\u0600" <= ch <= "\u06ff" for ch in d)


def test_heuristic_planner_covers_all_ten() -> None:
    plans = [draft_plan(d) for d in DESCRIPTIONS]
    names = {p.name for p in plans}
    assert len(names) >= 6  # تنوع نوايا حقيقي
    for plan in plans:
        assert plan.validate() == [], (plan.name, plan.validate())


def test_heuristic_is_deterministic() -> None:
    for d in DESCRIPTIONS:
        assert draft_plan(d).to_dict() == draft_plan(d).to_dict()


def test_known_intents_documented() -> None:
    ids = known_intents()
    assert "todo" in ids and "bookings" in ids and "blog" in ids


def test_phase1_acceptance_gate_first_run() -> None:
    """البوابة الرسمية: 10/10 توليدًا، ≥8/10 اختبارات أولية من أول تشغيل.

    اختبارات fastapi-api تستخدم importorskip — بدون fastapi تُحسب skip
    (كود خروج 0). CI يثبّت fastapi+httpx في وظيفة phase1 ليجري الفحص الحقيقي.
    """
    result: GateResult = run_acceptance_gate(run_tests=True, per_project_timeout=240)

    assert result.generated == 10, result.table_ar()
    assert result.passed >= GATE_MIN_PASSED, result.table_ar()
    assert result.ok, result.table_ar()

    # كل وصف على قالب مناسب من المخطط الاستدلالي
    templates = {r.name: r.template for r in result.rows}
    assert templates["todo-cli"] == "python-cli"
    assert templates["blog-site"] == "static-site"
    assert templates["bookings-api"] == "fastapi-api"
