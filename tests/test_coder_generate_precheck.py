"""اختبارات المولّد والفحص والـ RECEIPT (D12–14 وD19)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from zyko.coder.generate import (
    INIT_COMMIT_MSG,
    build_all_files,
    materialize,
)
from zyko.coder.plan import ProjectPlan
from zyko.coder.precheck import (
    check_directory,
    check_source_tree,
    run_project_tests,
)
from zyko.coder.receipt import receipt_md
from zyko.coder.templates import GenFile, build_tree


def _plan(template: str = "python-cli") -> ProjectPlan:
    return ProjectPlan(
        name="gen-demo",
        template=template,
        description="مشروع توليد للفحص الحتمي",
        modules=("tasks",),
        run_commands=("gen-demo --help",),
    )


# --------------------------------------------------------------------------- D12–13


def test_materialize_writes_full_tree(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    result = materialize(_plan(), out, git_init=False)
    assert (out / "src" / "gen_demo" / "core.py").is_file()
    assert (out / "RECEIPT.md").is_file()
    assert "RECEIPT.md" in result.files and "pyproject.toml" in result.files
    assert result.git_committed is False


def test_materialize_refuses_nonempty_dir(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    out.mkdir()
    (out / "x.txt").write_text("عمل المستخدم", encoding="utf-8")
    with pytest.raises(FileExistsError):
        materialize(_plan(), out, git_init=False)


def test_git_initial_commit_arabic_and_deterministic(tmp_path: Path) -> None:
    r1 = materialize(_plan(), tmp_path / "a", git_init=True)
    r2 = materialize(_plan(), tmp_path / "b", git_init=True)
    assert r1.git_committed and r2.git_committed

    def log(path: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(path), "log", "--format=%an|%ae|%s|%aI"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    l1, l2 = log(tmp_path / "a"), log(tmp_path / "b")
    assert "zyko-coder" in l1 and INIT_COMMIT_MSG in l1
    assert "2026-01-01T00:00:00" in l1  # git يطبع +00:00 كـ Z في %aI
    assert l1 == l2  # حتمية كاملة: نفس المستودع بايت-ببايت

    diff = subprocess.run(
        ["git", "-C", str(tmp_path / "b"), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    diff_a = subprocess.run(
        ["git", "-C", str(tmp_path / "a"), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert diff == diff_a


def test_receipt_deterministic_and_complete(tmp_path: Path) -> None:
    plan = _plan()
    t1 = build_all_files(plan)
    t2 = build_all_files(plan)
    assert t1["RECEIPT.md"].content == t2["RECEIPT.md"].content
    body = t1["RECEIPT.md"].content
    assert "قائمة" in body or "وصف" in body
    assert plan.description in body
    assert '"name": "gen-demo"' in body
    assert "| `src/gen_demo/core.py` |" in body  # كل ملف مع سببه
    assert "sha256" in body

    # سجل نماذج اختياري يظهر
    t3 = build_all_files(plan)
    t3["RECEIPT.md"] = receipt_md(
        plan,
        t3,
        model_log=[{"role": "planner", "model": "qwen2.5-coder:3b", "note": "تعبئة المخطط"}],
    )
    assert "qwen2.5-coder:3b" in t3["RECEIPT.md"].content
    assert "تعبئة حتمية بلا نموذج" not in t3["RECEIPT.md"].content


# --------------------------------------------------------------------------- D14


def test_precheck_passes_template_tree() -> None:
    for template in ("python-cli", "static-site"):
        report = check_source_tree(build_all_files(_plan(template)))
        assert report.ok, report.problems
        assert report.py_files >= 1


def test_precheck_rejects_broken_python() -> None:
    tree = build_tree(_plan())
    tree["src/gen_demo/broken.py"] = GenFile(
        "src/gen_demo/broken.py", "def f(:\n  pass\n", "ملف مكسور عمدًا"
    )
    report = check_source_tree(tree)
    assert not report.ok
    assert any("broken.py" in p and "مكسور" in p for p in report.problems)


def test_precheck_rejects_rtl_error_in_css() -> None:
    tree = build_tree(_plan("static-site"))
    tree["css/bad.css"] = GenFile(
        "css/bad.css",
        '[dir="rtl"] .x { text-align: left; }\n',
        "محاذاة فيزيائية داخل سياق RTL — خطأ RTL-CSS-001",
    )
    report = check_source_tree(tree)
    assert not report.ok
    assert any("RTL-CSS" in p for p in report.problems)


def test_precheck_ignores_rtl_info_and_warnings() -> None:
    tree = build_tree(_plan("static-site"))
    # قيمة فيزيائية بلا سياق RTL = تحذير فقط — لا يحجب التسليم
    tree["css/warn.css"] = GenFile("css/warn.css", ".y { float: left; }\n", "تحذير غير حاجب")
    report = check_source_tree(tree)
    assert report.ok, report.problems


def test_check_directory_on_disk(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    materialize(_plan(), out, git_init=False)
    report = check_directory(out)
    assert report.ok, report.problems

    (out / "bad.py").write_text("1 +\n", encoding="utf-8")
    report2 = check_directory(out)
    assert not report2.ok


def test_check_directory_rejects_non_utf8(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    out.mkdir()
    (out / "x.txt").write_bytes(b"\xff\xfe\x00binary")
    report = check_directory(out)
    assert not report.ok
    assert any("UTF-8" in p for p in report.problems)


def test_run_project_tests_pass_and_fail(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    (good / "test_ok.py").write_text("def test_x():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    report = run_project_tests(good)
    assert report.ok, report.test_output_tail

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "test_no.py").write_text("def test_y():\n    assert False\n", encoding="utf-8")
    report2 = run_project_tests(bad)
    assert not report2.ok
    assert report2.problems
