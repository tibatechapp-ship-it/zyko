"""تحصين ما بعد الدمج — واجهة zyko.coder السطرية: كل مسار رفض موثق يُختبر.

جولة 17 دمجت محرك multiplan ورفعت الإصدار إلى 0.41.0، وفشل CI كشف أن
مسارات الرفض في ``cmd_new``/``cmd_check`` غير مغطاة. هذه الملف يغلقها
سلوكيًا لا سطريًا: كل اختبار يحكي عقدًا معلنًا في الوحدة نفسها —
لا كتابة قبل الموافقة، ولا نصف مشروع على فشل، وكل رفض عربي يُطبع.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from zyko.coder.__main__ import _is_approval, main
from zyko.coder.plan import PlanValidationError
from zyko.coder.precheck import PrecheckReport

DESCRIPTION = "أداة سطرية لعدّ الكلمات في ملف نصي"


# ------------------------------------------------------------------ الموافقة
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("y", True),
        ("نعم", True),
        ("ن", True),
        ("no", False),
        ("لا", False),
        ("", False),
    ],
    ids=["y", "arabic-yes", "arabic-n", "no", "arabic-no", "empty"],
)
def test_approval_matrix_is_exact_not_prefixy(answer: str, expected: bool) -> None:
    """عقد القائمتين المتجانستين: y/yes لاتيني ونعم/ن عربي — لا قبول بالبادئة."""
    assert _is_approval(answer) is expected


# ------------------------------------------------------------------ plan
def test_plan_json_output_roundtrips_through_from_dict(capsys: pytest.CaptureFixture) -> None:
    """‏--json يطبع مخططًا يُعاد بناؤه من from_dict — العقد نفسه للنموذج."""
    rc = main(["plan", DESCRIPTION, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["template"] in {"python-cli", "fastapi-api", "static-site"}
    assert payload["description"] == DESCRIPTION.strip()


def test_new_catches_planner_validation_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """المخطِّط الصارم (النموذج الحقيقي) قد يرفض — CLI يلتقط ويرفض بلا كتابة (2)."""

    def _strict(_description: str) -> object:
        raise PlanValidationError(["الوصف أقصر من العقد المعلن"])

    monkeypatch.setattr("zyko.coder.__main__.draft_plan", _strict)
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir)])
    assert rc == 2
    assert "الوصف أقصر" in capsys.readouterr().err
    assert not out_dir.exists()  # لا نصف مشروع على فشل المخطط


# ------------------------------------------------------------------ new
def test_new_approval_eof_cancels_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """EOF على سؤال الموافقة = إلغاء صريح — لا كتابة صامتة ولا تعليق."""

    def _eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir)])
    assert rc == 1
    assert "أُلغي" in capsys.readouterr().out
    assert not out_dir.exists()


def test_new_rejected_answer_cancels_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """رفض صريح على الموافقة يوقف كل شيء — البوابة قبل أول بايت."""
    monkeypatch.setattr("builtins.input", lambda _prompt: "لا")
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir)])
    assert rc == 1
    assert "أُلغي" in capsys.readouterr().out
    assert not out_dir.exists()


def test_new_refuses_nonempty_target_directory(
    capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """مجلد إخراج غير فارغ = FileExistsError → رمز 2 — لا كتابة فوق عمل قائم."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "قيّم-قائمة.txt").write_text("عمل قائم", encoding="utf-8")
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes"])
    assert rc == 2
    assert "غير فارغ" in capsys.readouterr().err


def test_new_git_commit_is_printed_and_real(capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    """مع git متاحًا: التزام أول عربي يُطبع ويُتحقق منه من القرص لا من الوعد."""
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes"])
    assert rc == 0
    assert "التزام أول عربي" in capsys.readouterr().out
    log = Path(out_dir) / ".git"
    assert log.is_dir()


def test_new_git_unavailable_is_skipped_with_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏git تعطّل ≠ فشل المشروع: تخطٍّ موثق بالسبب يُطبع (لا صمت)."""
    import subprocess

    def _no_git(root: Path, *args: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="not found")

    monkeypatch.setattr("zyko.coder.generate._git", _no_git)
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes"])
    assert rc == 0
    assert "تخطّي" in capsys.readouterr().out


def test_new_no_git_flag_skips_silently_but_writes(
    capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏--no-git عقد صريح: المشروع يُكتب وبلا سطر git إطلاقًا."""
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes", "--no-git"])
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "التزام أول عربي" not in out_text and "تخطّي" not in out_text
    assert (out_dir / "RECEIPT.md").is_file()


def test_new_static_failure_rejects_with_problems(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """فحص ثابت فاشل بعد التوليد = رفض صريح (1) بمشاكل مفصّلة لا رمز صامت."""
    report = PrecheckReport()
    report.add_problem("RTL-PY-001: قائمة مختلطة الاتجاه")
    monkeypatch.setattr("zyko.coder.__main__.check_source_tree", lambda _tree: report)
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "فشل" in err and "RTL-PY-001" in err


def test_new_run_tests_failure_reports_and_rejects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏--run-tests مع بوابة فاشلة = رفض (1) بطرف مخرجات الاختبار."""
    report = PrecheckReport()
    report.add_problem("اختبار العدّ فشل")
    monkeypatch.setattr("zyko.coder.__main__.full_gate", lambda *_a, **_k: report)
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes", "--run-tests"])
    assert rc == 1
    assert "فشل" in capsys.readouterr().err


def test_new_run_tests_success_prints_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏--run-tests مع بوابة نظيفة = نجاح موثق (0) لا سطر أخضر زور."""
    monkeypatch.setattr("zyko.coder.__main__.full_gate", lambda *_a, **_k: PrecheckReport())
    out_dir = tmp_path / "out"
    rc = main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes", "--run-tests"])
    assert rc == 0
    assert "مرّت" in capsys.readouterr().out


# ------------------------------------------------------------------ check
def test_check_generated_project_is_clean(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """فحص مشروع مولَّد فعليًا: نظيف بعدد ملفاته الحقيقي — لا إبهام."""
    out_dir = tmp_path / "out"
    assert main(["new", "--plan", DESCRIPTION, "--out", str(out_dir), "--yes"]) == 0
    capsys.readouterr()
    rc = main(["check", str(out_dir)])
    out = capsys.readouterr().out
    assert rc == 0 and "نظيف" in out
    assert "بايثون" in out and "أخرى" in out


def test_check_run_tests_ok_prints_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏check --run-tests مع اختبارات ناجحة = سطر نجاح ورمز 0."""
    monkeypatch.setattr("zyko.coder.precheck.run_project_tests", lambda _root: PrecheckReport())
    rc = main(["check", str(tmp_path), "--run-tests"])
    assert rc == 0
    assert "مرّت" in capsys.readouterr().out


def test_check_run_tests_fail_returns_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    """‏check --run-tests مع اختبارات فاشلة = رمز 1 رغم نظافة الفحص الساكن."""
    report = PrecheckReport()
    report.add_problem("اختبار فاشل")
    monkeypatch.setattr("zyko.coder.precheck.run_project_tests", lambda _root: report)
    rc = main(["check", str(tmp_path), "--run-tests"])
    assert rc == 1
    assert "فشل" in capsys.readouterr().err


# ------------------------------------------------------------------ التشغيل المباشر
def test_module_main_entrypoint_runs_plan_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """‏python -m zyko.coder.__main__ يعمل من __main__ نفسه — نقطة الدخول الموثقة."""
    monkeypatch.setattr(sys, "argv", ["zyko-coder", "plan", DESCRIPTION])
    sys.modules.pop("zyko.coder.__main__", None)  # إعادة تنفيذ نظيفة بلا تحذير الكاش
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("zyko.coder.__main__", run_name="__main__")
    assert excinfo.value.code == 0
    assert DESCRIPTION.strip() in capsys.readouterr().out
