"""اختبارات طاقم التوليد الثلاثي (D15–16): التوجيهات العربية وربط الطاقم."""

from __future__ import annotations

import json

import pytest

from zyko.coder.crew_prompts import (
    CHECKER_SYSTEM,
    CODER_SYSTEM,
    PLANNER_SYSTEM,
    build_check_crew,
    build_plan_crew,
    extract_plan_json,
    parse_plan,
    planner_task,
    validate_templates_conform,
)


def test_planner_prompt_mentions_three_templates_and_schema_rules() -> None:
    for token in ("python-cli", "fastapi-api", "static-site", '"name"', '"modules"', "JSON"):
        assert token in PLANNER_SYSTEM, token
    validate_templates_conform()  # الحارس: أي قالب جديد يجب أن يدخل التوجيه


def test_coder_prompt_forbids_touching_structure_files() -> None:
    for token in ("pyproject.toml", "tests/", "RECEIPT.md", "ast.parse"):
        assert token in CODER_SYSTEM, token


def test_checker_prompt_hybrid_order_honest() -> None:
    # الفحص الحتمي أولًا — المراجع فوق التقرير لا بمعزله
    assert "الفاحص الحتمي" in CHECKER_SYSTEM
    assert "verdict" in CHECKER_SYSTEM


def test_extract_plan_json_tolerates_fences_and_prose() -> None:
    raw = 'إليك المخطط:\n```json\n{"name": "todo-cli", "template": "python-cli"}\n```\nشكرًا'
    data = extract_plan_json(raw)
    assert data["name"] == "todo-cli"


def test_extract_plan_json_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        extract_plan_json("لا يوجد JSON هنا إطلاقًا")
    with pytest.raises(ValueError):
        extract_plan_json("{name: بدون اقتباسات}")


def test_parse_plan_validates_strictly() -> None:
    good = json.dumps(
        {
            "name": "bookings-api",
            "template": "fastapi-api",
            "description": "حجوزات عيادة",
            "modules": ["bookings"],
            "dependencies": ["fastapi>=0.110"],
            "run_commands": ["uvicorn app.main:app"],
        },
        ensure_ascii=False,
    )
    plan = parse_plan(f"```json\n{good}\n```")
    assert plan.template == "fastapi-api"

    bad = json.dumps({"name": "X", "template": "nope", "description": "قصير"})
    from zyko.coder.plan import PlanValidationError

    with pytest.raises(PlanValidationError):
        parse_plan(bad)


def test_planner_task_embeds_description() -> None:
    task = planner_task("قائمة مهام للجامعة")
    assert "قائمة مهام للجامعة" in task
    assert '"template"' in task


class _FakeAgent:
    """بديل Agent للفحص البنيوي — لا يستدعي أي نموذج."""

    def __init__(
        self, router, *, name: str = "agent", system: str | None = None, **_: object
    ) -> None:
        self.router = router
        self.name = name
        self.system = system


class _FakeRouter:
    pass


def test_build_plan_crew_structure_with_fake_router(monkeypatch: pytest.MonkeyPatch) -> None:
    import zyko.agents as agents_mod
    import zyko.crew.engine as engine_mod

    monkeypatch.setattr(agents_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(engine_mod, "Agent", _FakeAgent)
    crew = build_plan_crew(_FakeRouter())
    assert [s.agent.name for s in crew.steps] == ["planner", "coder"]
    assert [s.output_key for s in crew.steps] == ["plan_json", "files_json"]
    # قالب المبرمج يستشهد بمخرَج المخطِّط
    assert "{plan_json}" in crew.steps[1].task
    # توجيهات النظام العربية مرّت للموكلات
    assert crew.steps[0].agent.system == PLANNER_SYSTEM
    assert crew.steps[1].agent.system == CODER_SYSTEM
    # الاستيراد المُحوَّل استُخدم


def test_build_check_crew_single_step(monkeypatch: pytest.MonkeyPatch) -> None:
    import zyko.agents as agents_mod
    import zyko.crew.engine as engine_mod

    monkeypatch.setattr(agents_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(engine_mod, "Agent", _FakeAgent)
    crew = build_check_crew(_FakeRouter())
    assert len(crew.steps) == 1
    assert crew.steps[0].agent.system == CHECKER_SYSTEM
    assert crew.steps[0].output_key == "verdict_json"
