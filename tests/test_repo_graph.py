"""اختبارات مرساة رسم المستودع البياني (الموجة 26 — زبدة Orbit بأسلوب zyko).

العقد المرساة: العقد ملفات شجرة فقط، الحواف قابلة للتحقق سطراً بسطر،
الاستيراد الخارجي وحش لا يدخل، الجوار حتمي بالبايت، والرسم لا يسقط.
"""

from __future__ import annotations

import json

import pytest

from zyko.reviewer.repo_graph import (
    build_repo_graph,
    graph_to_json,
    neighborhood,
    neighborhood_lines,
    neighborhood_note_for,
)


@pytest.fixture()
def tree(tmp_path):
    """شجرة مصغّرة: حزمة + مصدر + أداة + اختبار + ملف خارجي الاستيراد."""
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "core.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "leaf.py").write_text("from ..core import run\n\nX = run()\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import json\nfrom pkg.core import run\nfrom pkg import VALUE\n\nOUT = run() + VALUE\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text(
        "import pytest\nfrom pkg.core import run\n\ndef test_ok():\n    assert run() == 1\n",
        encoding="utf-8",
    )
    return tmp_path


def test_nodes_are_tree_files_only(tree):
    g = build_repo_graph(tree)
    assert set(g.files) == {
        "app.py",
        "pkg/__init__.py",
        "pkg/core.py",
        "pkg/sub/__init__.py",
        "pkg/sub/leaf.py",
        "tests/test_core.py",
    }


def test_import_edge_resolved_to_file(tree):
    g = build_repo_graph(tree)
    assert ("app.py", "pkg/core.py") in g.import_edges
    assert ("app.py", "pkg/__init__.py") in g.import_edges
    assert ("pkg/sub/leaf.py", "pkg/core.py") in g.import_edges  # نسبي بمستوى واحد


def test_external_import_never_becomes_node_or_edge(tree):
    g = build_repo_graph(tree)
    assert not any(b in ("json", "os", "sys") for _, b in g.import_edges)
    assert not any(a == "app.py" and b == "json" for a, b in g.import_edges)


def test_test_edge_only_when_test_imports_source(tree):
    g = build_repo_graph(tree)
    assert ("tests/test_core.py", "pkg/core.py") in g.test_edges
    # مصدر يستورد مصدراً ليس حافة اختبار
    assert ("pkg/sub/leaf.py", "pkg/core.py") not in g.test_edges


def test_neighborhood_exact(tree):
    g = build_repo_graph(tree)
    # الاختبار يستورد pkg.core لا app.py — فجوار app بلا اختبارات
    assert neighborhood(g, "app.py") == {
        "file": "app.py",
        "imports": ["pkg/__init__.py", "pkg/core.py"],
        "imported_by": [],
        "tests": [],
        "tested_by": [],
    }
    # جوار المصدر المستورَد يحمل الاختبار العكسي
    assert neighborhood(g, "pkg/core.py")["tested_by"] == ["tests/test_core.py"]


def test_neighborhood_unknown_file_is_named_rejection(tree):
    g = build_repo_graph(tree)
    with pytest.raises(KeyError):
        neighborhood(g, "ghost.py")


def test_byte_determinism_two_builds_identical(tree):
    a = graph_to_json(build_repo_graph(tree))
    b = graph_to_json(build_repo_graph(tree))
    assert a == b
    # التسلسل حتمي: المفاتيح مرتبة والمسارات مرتبة
    payload = json.loads(a)
    assert payload["import_edges"] == sorted(payload["import_edges"])
    assert payload["files"] == sorted(payload["files"])


def test_empty_tree_no_crash(tmp_path):
    g = build_repo_graph(tmp_path)
    assert g.files == ()
    assert g.import_edges == ()
    assert g.test_edges == ()


def test_unparsable_file_yields_no_edges_from_it(tmp_path):
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("import broken\n", encoding="utf-8")
    g = build_repo_graph(tmp_path)
    assert "broken.py" in g.files  # العقدة موجودة
    # لا حواف «منه» — عجز موثق بسكوت مقصود؛ والحافة «إليه» مشروعة
    # (حسم الاستيراد بالأسماء لا يحتاج تحليل الهدف)
    assert not any(a == "broken.py" for a, _ in g.import_edges)
    assert ("ok.py", "broken.py") in g.import_edges


# ------------------------------------------ تغذية التخطيط بجوار الرسم (الموجة 28)


def test_neighborhood_lines_sections_exact(tree):
    g = build_repo_graph(tree)
    # core.py بلا استيرادات داخلية — القسمان الموجودان فقط بالترتيب الثابت
    assert neighborhood_lines(g, "pkg/core.py") == (
        "يُستورد منه: app.py, pkg/sub/leaf.py",
        "اختبارات تستورده: tests/test_core.py",
    )


def test_neighborhood_lines_imports_section_first(tree):
    g = build_repo_graph(tree)
    lines = neighborhood_lines(g, "app.py")
    assert lines[0] == "يستورد: pkg/__init__.py, pkg/core.py"


def test_neighborhood_lines_isolated_file_named_line(tree):
    g = build_repo_graph(tree)
    assert neighborhood_lines(g, "pkg/sub/__init__.py") == (
        "الملف pkg/sub/__init__.py بلا حواف استيراد أو تغطية اختبارية داخل السقف المعلن",
    )


def test_neighborhood_lines_unknown_file_empty_not_exception(tree):
    g = build_repo_graph(tree)
    # اختلاف العقد الموثق عن neighborhood: مسار خارج السقف ⇒ فراغ معلن لا KeyError —
    # لأن المختار من شجرة git قد يقع خارج سقف المشي على القرص
    assert neighborhood_lines(g, "ghost.py") == ()


def test_neighborhood_lines_byte_deterministic(tree):
    a = neighborhood_lines(build_repo_graph(tree), "pkg/core.py")
    b = neighborhood_lines(build_repo_graph(tree), "pkg/core.py")
    assert a == b


def test_note_for_target_with_environment(tree):
    (tree / "pyproject.toml").write_text("[project]\n", encoding="utf-8")  # علامة الجذر
    note = neighborhood_note_for(tree / "pkg" / "core.py")
    # الأقسام لا تكرر اسم الملف — المستهدف مسمّى في طلب الخطة أصلاً
    assert "app.py" in note and "tests/test_core.py" in note


def test_note_for_isolated_file_is_empty(tree):
    # عزل كامل ⇒ لا غذاء تخطيط — العقد الموثقة: فراغ لا سطر عزلة
    assert neighborhood_note_for(tree / "pkg" / "sub" / "__init__.py") == ""


def test_note_for_missing_or_non_python_is_empty(tree):
    assert neighborhood_note_for(tree / "ghost.py") == ""
    (tree / "notes.txt").write_text("hi", encoding="utf-8")
    assert neighborhood_note_for(tree / "notes.txt") == ""


def test_note_for_byte_deterministic(tree):
    (tree / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    a = neighborhood_note_for(tree / "pkg" / "core.py")
    b = neighborhood_note_for(tree / "pkg" / "core.py")
    assert a == b and a != ""
