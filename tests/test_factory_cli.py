"""اختبارات بوابة المصنع الموحدة (المرحلة 7): تفويض حرفي وخريطة وبوابات مجمعة."""

from __future__ import annotations

import pytest

from zyko.cli import main as cli_main
from zyko.factory.cli import main as factory_main
from zyko.fixer.__main__ import main as fixer_main
from zyko.pipeline.__main__ import main as pipeline_main
from zyko.workspace.__main__ import main as workspace_main

CLEAN = "def add(a, b):\n    return a + b\n"


# ------------------------------------------------------------- الخريطة
def test_bare_factory_prints_map(capsys: pytest.CaptureFixture[str]) -> None:
    assert factory_main([]) == 0
    out = capsys.readouterr().out
    assert "المصنع ZYKO" in out
    assert "العقود الثلاثة" in out
    assert "suggestion_ar" in out


def test_factory_map_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert factory_main(["map"]) == 0
    out = capsys.readouterr().out
    for unit in ("fix", "pipeline", "workspace", "baseline", "gates"):
        assert unit in out


def test_factory_via_main_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["factory", "map"]) == 0
    assert "المصنع ZYKO" in capsys.readouterr().out


# ----------------------------------------------- تفويض fix (نفس السلوك حرفيًا)
def test_factory_fix_missing_path_exit2(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = "/nonexistent/zyko-factory-test/بدون"
    assert factory_main(["fix", "--path", missing]) == 2
    err = capsys.readouterr().err
    assert "المسار غير موجود" in err


def test_factory_fix_delegates_identically_to_fixer(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """بوابة المصنع = وحدة المُصلِح: نفس المدخل ⇒ نفس الخرج بايتيًا."""
    src = tmp_path / "m.py"  # type: ignore[attr-defined]
    src.write_text(CLEAN, encoding="utf-8")
    argv = ["fix", "--path", str(src), "--format", "summary"]

    rc_direct = fixer_main(argv)
    out_direct = capsys.readouterr().out
    rc_factory = factory_main(argv)
    out_factory = capsys.readouterr().out

    assert rc_direct == rc_factory == 0
    assert out_direct == out_factory


def test_factory_fix_non_python_dir_exit2(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    assert factory_main(["fix", "--path", str(tmp_path)]) == 2  # type: ignore[attr-defined]
    assert "لا ملفات بايثون" in capsys.readouterr().err


# ----------------------------------------------------- تفويض pipeline
def test_factory_pipeline_dry_run(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    rc = factory_main(
        [
            "pipeline",
            "--description",
            "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها",
            "--out",
            str(tmp_path / "proj"),  # type: ignore[attr-defined]
            "--dry-run",
            "--fail-under",
            "0",
            "--format",
            "summary",
        ]
    )
    assert rc == 0
    assert "الحلقة اكتملت" in capsys.readouterr().out


def test_factory_pipeline_parity_with_module(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        "run",
        "--description",
        "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها",
        "--out",
        str(tmp_path / "unused"),  # type: ignore[attr-defined]
        "--dry-run",
        "--fail-under",
        "0",
        "--format",
        "summary",
    ]
    rc_module = pipeline_main(argv)
    out_module = capsys.readouterr().out
    rc_factory = factory_main(["pipeline", *argv[1:]])
    out_factory = capsys.readouterr().out
    assert rc_module == rc_factory == 0
    assert out_module == out_factory


# ---------------------------------------------------- تفويض workspace
def test_factory_workspace_missing_dir_exit2(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    assert factory_main(["workspace", "--src", str(tmp_path / "لا-يوجد")]) == 2  # type: ignore[attr-defined]
    captured = capsys.readouterr()
    assert "المسح" in captured.out  # تقرير الفشل المهيكل يُطبع في stdout


def test_factory_workspace_dry_run_on_sample(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = factory_main(
        [
            "workspace",
            "--src",
            "samples/workspace/small_tool",
            "--fail-under",
            "0",
            "--format",
            "summary",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "فُحص 3 ملفًا" in out


def test_factory_workspace_parity_with_module(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = [
        "run",
        "--src",
        "samples/workspace/small_tool",
        "--fail-under",
        "0",
        "--format",
        "summary",
    ]
    rc_module = workspace_main(argv)
    out_module = capsys.readouterr().out
    rc_factory = factory_main(["workspace", *argv[1:]])
    out_factory = capsys.readouterr().out
    assert rc_module == rc_factory
    assert out_module == out_factory


# ------------------------------------------------------- البوابات المجمعة
def test_factory_gates_all_green(capsys: pytest.CaptureFixture[str]) -> None:
    """بوابات المراحل الأربع (24 بوابه) ناجحة في أمر واحد."""
    rc = factory_main(["gates"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "4/4" in out
    assert "المصنع مقبول" in out
    # جدول كل مرحلة ظهر
    assert out.count("المرحلة 3") >= 1
    assert out.count("المرحلة 4") >= 1
    assert out.count("المرحلة 5") >= 1
    assert out.count("المرحلة 6") >= 1


# ---------------------------------------------------- تفويض baseline
def test_factory_baseline_update_and_check(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """تفويض baseline حرفيًا: update يسجّل، check يقرأ — نفس سلوك الوحدة."""
    src = tmp_path / "proj"  # type: ignore[attr-defined]
    src.mkdir()
    (src / "m.py").write_text("x = 1\n", encoding="utf-8")
    rc = factory_main(["baseline", "update", "--src", str(src), "--format", "summary"])
    assert rc == 0
    baseline_file = src / ".zyko" / "baseline.json"
    assert baseline_file.exists()
    capsys.readouterr()  # تفرّغ الخرج قبل فحص التكافؤ التالي
    rc2 = factory_main(["baseline", "check", "--src", str(src), "--format", "summary"])
    out_check = capsys.readouterr().out
    assert rc2 == 0
    # التكافؤ مع وحدة baseline: نفس الأمر عبر الوحدة نفسه الخرج
    from zyko.baseline.__main__ import main as baseline_main

    rc3 = baseline_main(["check", "--src", str(src), "--format", "summary"])
    out_direct = capsys.readouterr().out
    assert rc3 == rc2
    assert out_direct == out_check


def test_factory_baseline_check_missing_baseline_exit1(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """check بلا خط أساس ⇒ ملاحظة «سجّل update أولًا» وخروج 1 (عقد الوحدة)."""
    src = tmp_path / "empty"  # type: ignore[attr-defined]
    src.mkdir()
    (src / "a.py").write_text("y = 2\n", encoding="utf-8")
    rc = factory_main(["baseline", "check", "--src", str(src)])
    assert rc == 1
    assert "update" in capsys.readouterr().out
