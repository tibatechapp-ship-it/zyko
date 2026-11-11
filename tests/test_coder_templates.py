"""اختبارات القوالب الثلاثة (D8–9): البنية والحتمية وسلامة الأسماء."""

from __future__ import annotations

import ast

import pytest

from zyko.coder.plan import ProjectPlan
from zyko.coder.templates import BUILDERS, GenFile, build_tree, cls_name


def _plan(template: str, modules: tuple[str, ...]) -> ProjectPlan:
    return ProjectPlan(
        name="demo-app",
        template=template,
        description="مشروع تجريبي لاختبار القوالب بالعربية",
        modules=modules,
        run_commands=("demo-app --help",),
    )


def test_registry_has_exactly_three_builders() -> None:
    assert set(BUILDERS) == {"python-cli", "fastapi-api", "static-site"}


def test_cls_name_from_snake_case() -> None:
    assert cls_name("task_items") == "TaskItems"
    assert cls_name("users") == "Users"


def test_python_cli_structure_and_syntax() -> None:
    tree = build_tree(_plan("python-cli", ("tasks", "reports")))
    for rel in (
        "pyproject.toml",
        ".gitignore",
        "README.md",
        "src/demo_app/__init__.py",
        "src/demo_app/core.py",
        "src/demo_app/cli.py",
        "src/demo_app/__main__.py",
        "tests/test_core.py",
    ):
        assert rel in tree, rel
    # كل بايثون يمر ast
    for rel, f in tree.items():
        if rel.endswith(".py"):
            ast.parse(f.content, filename=rel)
    # الحزمتان في pyproject وأمر الدخول
    pyproject = tree["pyproject.toml"].content
    assert 'name = "demo-app"' in pyproject
    assert 'demo-app = "demo_app.cli:main"' in pyproject
    # الوحدتان في CLI (حلقة بياناتية) وcore
    cli = tree["src/demo_app/cli.py"].content
    assert "for name in ('tasks', 'reports'):" in cli
    assert "mods.add_parser(name" in cli
    assert "class TasksStore" in tree["src/demo_app/core.py"].content
    assert "class ReportsStore" in tree["src/demo_app/core.py"].content


def test_fastapi_structure_and_modules() -> None:
    tree = build_tree(_plan("fastapi-api", ("bookings",)))
    for rel in ("pyproject.toml", "app/__init__.py", "app/main.py", "tests/test_api.py"):
        assert rel in tree, rel
    ast.parse(tree["app/main.py"].content, filename="app/main.py")
    main = tree["app/main.py"].content
    assert 'title="demo-app"' in main or "demo-app" in main
    assert "/health" in main
    assert "class BookingsIn" in main and "class BookingsOut" in main
    assert '@app.post("/bookings"' in main
    assert "fastapi>=0.110" in tree["pyproject.toml"].content


def test_static_site_rtl_by_construction() -> None:
    tree = build_tree(_plan("static-site", ("menu", "contact")))
    html = tree["index.html"].content
    assert 'dir="rtl"' in html and 'lang="ar"' in html
    assert 'id="menu"' in html and 'id="contact"' in html
    css = tree["css/style.css"].content
    for physical in (
        "text-align: left",
        "text-align: right",
        "margin-left",
        "padding-right",
        "float: left",
    ):
        assert physical not in css, physical
    assert "padding-inline" in css
    ast.parse(tree["tests/test_site.py"].content)


def test_determinism_same_plan_same_bytes() -> None:
    p1 = build_tree(_plan("python-cli", ("tasks",)))
    p2 = build_tree(_plan("python-cli", ("tasks",)))
    assert set(p1) == set(p2)
    for rel in p1:
        assert p1[rel].content == p2[rel].content, rel
        assert p1[rel].reason == p2[rel].reason, rel


def test_every_file_has_arabic_reason() -> None:
    for template, mods in (
        ("python-cli", ("tasks",)),
        ("fastapi-api", ("bookings",)),
        ("static-site", ("menu",)),
    ):
        for rel, f in build_tree(_plan(template, mods)).items():
            assert isinstance(f, GenFile)
            assert f.reason.strip(), rel


def test_multi_module_expansion_is_symmetric() -> None:
    one = build_tree(_plan("python-cli", ("tasks",)))
    two = build_tree(_plan("python-cli", ("tasks", "users")))
    # نفس الملفات (لا ملفات إضافية لكل وحدة — التوسيع داخل الملفات نفسها)
    assert set(one) == set(two)
    assert "class UsersStore" in two["src/demo_app/core.py"].content
    assert "class UsersStore" not in one["src/demo_app/core.py"].content


def test_unknown_template_raises() -> None:
    with pytest.raises(ValueError):
        build_tree(_plan("nope", ("x",)))
