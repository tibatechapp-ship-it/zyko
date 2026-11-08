"""اختبارات ProjectPlan المتحقق (D10–11)."""

from __future__ import annotations

import pytest

from zyko.coder.plan import (
    TEMPLATES,
    PlanValidationError,
    ProjectPlan,
    package_name,
    safe_slug,
)


def _valid(**overrides) -> ProjectPlan:
    base = dict(
        name="todo-cli",
        template="python-cli",
        description="قائمة مهام يومية بسيطة بالعربية",
        modules=("tasks",),
        dependencies=(),
        run_commands=("todo-cli --help",),
    )
    base.update(overrides)
    return ProjectPlan(**base)


def test_valid_plan_has_no_problems() -> None:
    assert _valid().validate() == []


def test_templates_registry_is_the_three_phase1_templates() -> None:
    assert TEMPLATES == ("python-cli", "fastapi-api", "static-site")


def test_missing_name_is_rejected_in_arabic() -> None:
    problems = _valid(name="").validate()
    assert problems and "الاسم" in problems[0]


def test_unsafe_name_is_rejected() -> None:
    for bad in ("Todo", "1abc", "has space", "طويل-عربي", "a" * 50, "-x"):
        problems = _valid(name=bad).validate()
        assert any("الاسم" in p for p in problems), bad


def test_unknown_template_rejected_with_choices() -> None:
    problems = _valid(template="django-app").validate()
    assert any("python-cli" in p for p in problems)


def test_missing_description_rejected() -> None:
    problems = _valid(description="  ").validate()
    assert any("الوصف" in p for p in problems)


def test_modules_required_and_identifiers_safe() -> None:
    problems = _valid(modules=()).validate()
    assert any("الوحدات ناقصة" in p for p in problems)

    for bad in ("Tasks", "with space", "class", "import", "حرف-عربي"):
        problems = _valid(modules=(bad,)).validate()
        assert any("الوحدة" in p for p in problems), bad


def test_duplicate_module_rejected() -> None:
    problems = _valid(modules=("tasks", "tasks")).validate()
    assert any("مكررة" in p for p in problems)


def test_dependency_format_validated() -> None:
    assert _valid(dependencies=("fastapi>=0.110", "uvicorn")).validate() == []
    for bad in (">=1.0", "fast api>=1", "pkg;python<3"):
        problems = _valid(dependencies=(bad,)).validate()
        assert any("الاعتمادية" in p for p in problems), bad


def test_run_commands_bounds() -> None:
    assert _valid(run_commands=("x",)).validate() == []
    problems = _valid(run_commands=("   ",)).validate()
    assert any("أمر تشغيل" in p for p in problems)


def test_from_dict_rejects_unknown_keys_listing_all_problems() -> None:
    with pytest.raises(PlanValidationError) as exc:
        ProjectPlan.from_dict(
            {
                "name": "todo-cli",
                "template": "python-cli",
                "description": "وصف كافٍ للقبول",
                "modules": ["tasks"],
                "surprise": 1,
                "another": True,
            }
        )
    msg = str(exc.value)
    assert "surprise" in msg and "another" in msg
    assert exc.value.problems  # كل المشاكل دفعة واحدة


def test_from_dict_rejects_non_list_modules() -> None:
    with pytest.raises(PlanValidationError) as exc:
        ProjectPlan.from_dict(
            {
                "name": "todo-cli",
                "template": "python-cli",
                "description": "وصف كافٍ للقبول",
                "modules": "tasks",
            }
        )
    assert any("قائمة نصوص" in p for p in exc.value.problems)


def test_from_dict_roundtrip() -> None:
    plan = _valid(dependencies=("rich>=13",))
    data = plan.to_dict()
    again = ProjectPlan.from_dict(data)
    assert again == plan
    assert again.to_dict() == data


def test_summary_ar_mentions_key_fields() -> None:
    s = _valid(display_name="مهامي").summary_ar()
    assert "مهامي" in s and "python-cli" in s and "tasks" in s


def test_safe_slug_cleans_and_falls_back() -> None:
    assert safe_slug("My App!!") == "my-app"
    assert safe_slug("  TODO__list  ") == "todo-list"
    assert safe_slug("أهلاً") == "my-app"
    assert safe_slug("", fallback="x") == "my-app"  # fallback قصير جدًا → الافتراضي


def test_package_name_derives_python_pkg() -> None:
    assert package_name("todo-cli") == "todo_cli"
