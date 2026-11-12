"""اختبارات تعدد العقول BestOfBrain: المرشحون يتنافسون، والبوابات تحكم.

بلا شبكة إطلاقًا: نقل مزيف يُحقن في عقل Ollama، ومرشحون حتميون
(المخطط) — تُختبر منافسة كاملة: فوز المحاولة الأولى، احتياط المخطط
بعد رفض النموذج، رفض نص عدائي من بوابته الخاصة، فشل الجميع،
وتوثيق القصة كاملة في الإيصال — ثم سطر الأوامر.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from zyko.ai.best_of_brain import BestOfBrain
from zyko.ai.brains import Brain, GatedBrain, PlannerBrain
from zyko.ai.cli import main as ai_main
from zyko.ai.ollama_brain import OllamaBrain
from zyko.ai.session import AISession
from zyko.mock_llm import get_scenario

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"

# نص المخطط الحتمي للهدف — مرجع ثابت يفوز به المرشح الاحتياطي
PLANNER_TEXT = PlannerBrain().propose(CLEAN_GOAL).text

PLAN_CLEAN = "\n".join(
    [
        "- وحدة tasks لإدارة المهام والذاكرة",
        "- واجهة سطر أوامر للإضافة والإتمام والإدراج",
        "- اختبارات وحدة أساسية للمسارات الثلاثة",
    ]
)


def _fake_transport(content: object) -> Any:
    """نقل مزيف يعيد استجابة جاهزة — يلتقط الحمولة في ``payloads``."""

    def call(payload: dict[str, Any]) -> Any:
        _fake_transport.payloads.append(payload)  # type: ignore[attr-defined]
        return content

    return call


_fake_transport.payloads = []  # type: ignore[attr-defined]


def _broken_transport() -> Any:
    """نقل مزيف يفشل دائمًا — يحاكي خادم Ollama المتوقف."""

    def call(payload: dict[str, Any]) -> Any:
        raise urllib.error.URLError("refused")

    return call


def _ollama(model: str = "m", transport: Any | None = None) -> OllamaBrain:
    return OllamaBrain(model=model, transport=transport if transport else _broken_transport())


# ============================================================ البناء
def test_empty_candidates_rejected_in_arabic() -> None:
    with pytest.raises(ValueError) as excinfo:
        BestOfBrain([])
    assert "عقل واحد على الأقل" in str(excinfo.value)


def test_name_composition_and_custom_override() -> None:
    assert BestOfBrain([PlannerBrain(), _ollama()]).name == "bestof:planner+ollama:m"
    assert BestOfBrain([PlannerBrain()], name="مخصص").name == "مخصص"


def test_deterministic_is_union_of_candidates() -> None:
    assert BestOfBrain([PlannerBrain(), PlannerBrain()]).deterministic is True
    assert BestOfBrain([PlannerBrain(), _ollama()]).deterministic is False


def test_candidates_exposed_in_gated_names() -> None:
    brain = BestOfBrain([PlannerBrain(), _ollama()])
    assert brain.candidates == ("gated:planner", "gated:ollama:m")


def test_best_of_brain_satisfies_brain_protocol() -> None:
    assert isinstance(BestOfBrain([PlannerBrain()]), Brain)  # type: ignore[arg-type]


# ============================================================ المنافسة
def test_first_candidate_wins_and_competition_stops() -> None:
    _fake_transport.payloads.clear()
    brain = BestOfBrain(
        [PlannerBrain(), _ollama(transport=_fake_transport({"message": {"content": PLAN_CLEAN}}))]
    )
    proposal = brain.propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLANNER_TEXT  # فاز المرشح الأول لا الثاني
    assert _fake_transport.payloads == []  # المرشح الثاني لم يُستشار إطلاقًا
    # أحكام الفائز (كلها خضراء — المخطط يفحص نفسه ثم الغلاف يعيد) ثم خلاصة المنافسة
    assert [v.gate for v in proposal.verdicts] == [
        "planner",
        "pii",
        "rtl",
        "pii",
        "rtl",
        "bestof",
    ]
    assert all(v.passed for v in proposal.verdicts)
    assert "فاز المرشح 1 من 2" in proposal.verdicts[-1].details_ar
    assert "من المحاولة الأولى" in proposal.verdicts[-1].details_ar


def test_fallback_to_planner_after_model_unreachable() -> None:
    brain = BestOfBrain([_ollama(model="غائب"), PlannerBrain()])
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLANNER_TEXT
    assert proposal.brain == "gated:bestof:ollama:غائب+planner"
    # أحكام الفائز (كلها خضراء) ثم خلاصة المنافسة ثم إعادة فحص الغلاف الخارجي
    gates = [v.gate for v in proposal.verdicts]
    assert gates == ["planner", "pii", "rtl", "pii", "rtl", "bestof", "pii", "rtl"]
    assert all(v.passed for v in proposal.verdicts)
    summary = proposal.verdicts[5]
    assert summary.passed
    assert "فاز المرشح 2 من 2" in summary.details_ar
    assert "(رُفض قبله 1:" in summary.details_ar
    assert "تعذّر الوصول إلى Ollama" in summary.details_ar  # قصة المرشح المرفوض محفوظة


def test_hostile_model_text_rejected_by_its_own_gates() -> None:
    dirty = get_scenario("suspicious").render(CLEAN_GOAL)  # نص فيه هاتف — PII
    brain = BestOfBrain(
        [_ollama(transport=_fake_transport({"message": {"content": dirty}})), PlannerBrain()]
    )
    proposal = brain.propose(CLEAN_GOAL)
    assert proposal.accepted  # المخطط أنقذ الجلسة
    assert proposal.text == PLANNER_TEXT
    summary = proposal.verdicts[-1]
    assert summary.passed
    assert "phone" in summary.details_ar  # قصة رفض PII للنموذج مطوية في الخلاصة


def test_all_candidates_fail_yields_arabic_rejection() -> None:
    brain = BestOfBrain(
        [
            _ollama(model="a"),  # خادم متوقف
            _ollama(model="b", transport=_fake_transport({"message": {"content": "   "}})),
        ]
    )
    proposal = brain.propose(CLEAN_GOAL)
    assert not proposal.accepted
    assert proposal.text == ""
    gates = [v.gate for v in proposal.verdicts]
    assert gates == ["bestof:1:gated:ollama:a", "bestof:2:gated:ollama:b", "bestof"]
    assert all(not v.passed for v in proposal.verdicts)
    summary = proposal.verdicts[-1]
    assert "فشل جميع المرشحين (2)" in summary.details_ar
    # دليل كل مرشح محفوظ بالترتيب
    assert "تعذّر الوصول إلى Ollama" in proposal.verdicts[0].details_ar
    assert "فارغًا" in proposal.verdicts[1].details_ar


def test_empty_goal_short_circuits_without_consulting_anyone() -> None:
    _fake_transport.payloads.clear()
    brain = BestOfBrain(
        [PlannerBrain(), _ollama(transport=_fake_transport({"message": {"content": PLAN_CLEAN}}))]
    )
    proposal = brain.propose("   ")
    assert not proposal.accepted
    assert proposal.text == ""
    assert _fake_transport.payloads == []  # لا مرشح استُشار
    assert "الهدف فارغ" in proposal.verdicts[-1].details_ar


def test_winner_text_passes_outer_gates_unchanged() -> None:
    """الغلاف الخارجي يعيد فحص النص الفائز — دفاع في العمق بلا تغيير نص."""
    brain = GatedBrain(BestOfBrain([PlannerBrain()]))
    proposal = brain.propose(CLEAN_GOAL)
    assert proposal.accepted
    assert [v.gate for v in proposal.verdicts] == [
        "planner",
        "pii",
        "rtl",
        "pii",
        "rtl",  # أحكام الفائز (المخطط يفحص نفسه + الغلاف)
        "bestof",  # خلاصة المنافسة
        "pii",
        "rtl",  # إعادة الفحص الخارجي — دفاع في العمق
    ]


# ============================================================ الجلسة الكاملة
def test_session_fallback_model_down_planner_rescues(tmp_path: Path) -> None:
    brain = GatedBrain(BestOfBrain([_ollama(model="m"), PlannerBrain()]))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert receipt.ok
    assert receipt.brain == "gated:bestof:ollama:m+planner"
    assert receipt.brain_deterministic is False  # نموذج في المنافسة ⇒ توثيق صريح
    assert receipt.plan is not None
    assert receipt.plan["brain"] == "gated:bestof:ollama:m+planner"
    assert receipt.plan["text"] == PLANNER_TEXT
    plan_step = next(s for s in receipt.steps if s.step == "plan")
    assert plan_step.ok
    assert "فاز المرشح 2 من 2" in plan_step.details_ar
    assert "تعذّر الوصول إلى Ollama" in plan_step.details_ar  # قصة المنافسة كاملة


def test_session_all_fail_rejects_before_any_write(tmp_path: Path) -> None:
    brain = GatedBrain(
        BestOfBrain([_ollama(model="a"), _ollama(model="b", transport=_fake_transport({}))])
    )
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert not receipt.ok
    assert receipt.failed_step == "plan"
    assert not (tmp_path / "proj").exists()  # الرفض قبل كتابة بايت واحد
    # الإيصال يوثّق كل المرشحين الفاشلين لا أولهم فقط
    details = next(s for s in receipt.steps if s.step == "plan").details_ar
    assert "تعذّر الوصول إلى Ollama" in details  # فشل المرشح الأول
    assert "غير مفهومة" in details  # فشل المرشح الثاني
    assert "فشل جميع المرشحين (2)" in details  # خلاصة المنافسة


def test_session_bestof_receipt_is_byte_deterministic(tmp_path: Path) -> None:
    brain = GatedBrain(BestOfBrain([_ollama(model="m"), PlannerBrain()]))
    r1 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "a" / "proj")
    r2 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "b" / "proj")
    assert r1.to_json() == r2.to_json()


def test_session_all_deterministic_composite_documented_as_such(tmp_path: Path) -> None:
    brain = GatedBrain(BestOfBrain([PlannerBrain(), PlannerBrain()]))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj", write=False)
    assert receipt.ok
    assert receipt.brain_deterministic is True


# ============================================================ سطر الأوامر
def test_cli_brain_bestof_requires_model(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--brain", "bestof", "--goal", CLEAN_GOAL, "--out", "/tmp/x"])
    assert rc == 2
    assert "--model" in capsys.readouterr().err


def test_cli_brain_bestof_model_down_planner_rescues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import ollama_brain as ob

    monkeypatch.setattr(ob, "_http_transport", lambda host, timeout: _broken_transport())
    rc = ai_main(
        [
            "run",
            "--brain",
            "bestof",
            "--model",
            "fake-model",
            "--goal",
            CLEAN_GOAL,
            "--out",
            str(tmp_path / "proj"),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["brain"] == "gated:bestof:ollama:fake-model+planner"
    assert payload["brain_deterministic"] is False
    assert payload["plan"]["text"] == PLANNER_TEXT
    plan_details = payload["steps"][1]["details_ar"]
    assert "فاز المرشح 2 من 2" in plan_details


def test_cli_brain_bestof_model_clean_wins_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import ollama_brain as ob

    monkeypatch.setattr(
        ob,
        "_http_transport",
        lambda host, timeout: _fake_transport({"message": {"content": PLAN_CLEAN}}),
    )
    rc = ai_main(
        [
            "run",
            "--brain",
            "bestof",
            "--model",
            "fake-model",
            "--goal",
            CLEAN_GOAL,
            "--out",
            str(tmp_path / "proj"),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan"]["text"] == PLAN_CLEAN  # النموذج فاز من المحاولة الأولى
    assert "من المحاولة الأولى" in payload["steps"][1]["details_ar"]


def test_map_documents_the_bestof_brain(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main(["map"]) == 0
    out = capsys.readouterr().out
    assert "--brain bestof" in out
    assert "منافسة عقول" in out
