"""اختبارات الوضع القائم ``--mode existing`` — عقل `zyko do` كاملاً خلف الجلسة.

ما تغلق هذه الاختبارات هو الفجوة التي كشفها الاختبار الواقعي على
psf/requests (docs/REAL_WORLD_TEST.md): جلسة الذكاء كانت موصولة بالمصنع
حصرياً — هدف «راجع وأصلح ملفاً قائماً» كان يولّد مشروعاً جديداً بدل
معالجة الملف. الآن النمط ``existing`` ينفّذ classify → route → run على
الملف الحقيقي عبر المحرّس والإيصال الموحّد، وبنفس بوابات الجلسة.

بلا شبكة وبلا نموذج: العقل الافتراضي ``PlannerBrain`` حتمي، والملفات
حقيقية في tmp_path — نفس عقود بقية طبقة الذكاء (حتمية بالبايت، لا كتابة
في التجريبي، رفض عربي موثق).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.ai.receipt import hash_file
from zyko.ai.session import EXISTING_GATE_TITLE, AISession

# ملف «مريض» عمداً: bare except قابل للإصلاح + دوال طويلة ومعاملات كثيرة
# وعمق تداخل — ملاحظات حقيقية بدرجة دون حد القبول الافتراضي.
SICK_CODE = '''"""وحدة مريضة عمداً لتدريب المراجع والمصلح."""


def risky(path):
    try:
        return open(path).read()
    except:
        return ""


def wide(a, b, c, d, e, f, g, h):
    if a:
        if b:
            if c:
                if d:
                    return a + b + c + d + e + f + g + h
    return 0
'''

GOAL_REVIEW = "راجع الملف التالي بدقة"
GOAL_FIX = "راجع وأصلح الملف المذكور"


def _make_file(tmp_path: Path, name: str = "sample.py") -> Path:
    target = tmp_path / name
    target.write_text(SICK_CODE, encoding="utf-8")
    return target


def _goal_with(target: Path, goal: str) -> str:
    return f"{goal} {target}"


def _step(receipt, name: str):
    return next(s for s in receipt.steps if s.step == name)


# ============================================================ الوضع الجاف
def test_existing_dry_run_runs_zyko_do_brain_on_real_file(tmp_path: Path) -> None:
    target = _make_file(tmp_path)
    sha_before = hash_file(target)
    receipt = AISession(mode="existing").run(
        _goal_with(target, GOAL_FIX), tmp_path / "out", write=False
    )
    assert receipt.ok, receipt.verdict_ar()
    gate = _step(receipt, "orchestrator")
    assert gate.ok
    assert gate.title_ar == EXISTING_GATE_TITLE
    # عقل `zyko do` كاملاً موثق في التفاصيل: تصنيف + خطة + بصمة سلسلة
    assert "التصنيف FIX" in gate.details_ar
    assert "[review]" in gate.details_ar and "[fix]" in gate.details_ar
    assert "chain_hash" in gate.details_ar
    # الدرجة الحالية موثقة بصدق، والحد يُفحص في الكتابة لا في التجريبي
    assert "الدرجة الحالية" in gate.details_ar
    # الملف لم يُلمس بايتاً واحداً
    assert hash_file(target) == sha_before
    assert receipt.files_written == []


def test_existing_review_only_goal_skips_fix(tmp_path: Path) -> None:
    target = _make_file(tmp_path)
    receipt = AISession(mode="existing").run(
        _goal_with(target, GOAL_REVIEW), tmp_path / "out", write=False
    )
    gate = _step(receipt, "orchestrator")
    assert gate.ok
    assert "التصنيف REVIEW" in gate.details_ar
    assert "[review]" in gate.details_ar
    assert "[fix]" not in gate.details_ar


# ============================================================ وضع الكتابة
def test_existing_write_mode_fixes_file_in_place(tmp_path: Path) -> None:
    target = _make_file(tmp_path)
    sha_before = hash_file(target)
    session = AISession(mode="existing", fail_under=0)
    receipt = session.run(_goal_with(target, GOAL_FIX), tmp_path / "out", write=True)
    gate = _step(receipt, "orchestrator")
    assert gate.ok, gate.details_ar
    # الإصلاح كتب في مكان الملف الأصلي (عقد `zyko do --write`) والبصمة تغيّرت
    assert hash_file(target) != sha_before
    assert receipt.files_written == [str(target)]
    assert str(target) in gate.evidence
    # الدرجة بعد الإصلاح موثقة ومتسقة مع المراجع
    from zyko.reviewer.engine import ReviewEngine

    assert receipt.min_score_after == ReviewEngine().review_file(target).score
    # ملخص الإصلاح المطبَّق بالتفصيل — لا «أُنجزت» العمياء
    assert "أُصلح" in gate.details_ar and "الدرجة" in gate.details_ar


def test_existing_write_mode_unreachable_threshold_rejects_honestly(tmp_path: Path) -> None:
    target = _make_file(tmp_path)
    receipt = AISession(mode="existing", fail_under=101).run(
        _goal_with(target, GOAL_FIX), tmp_path / "out", write=True
    )
    assert not receipt.ok
    assert receipt.failed_step == "orchestrator"
    gate = _step(receipt, "orchestrator")
    assert "دون الحد 101" in gate.details_ar
    assert "تبقى" in gate.details_ar


# ============================================================ الحراس
def test_existing_goal_without_real_file_rejected_arabic(tmp_path: Path) -> None:
    receipt = AISession(mode="existing").run(
        "راجع وأصلح src/غير_موجود.py", tmp_path / "out", write=False
    )
    assert not receipt.ok
    assert receipt.failed_step == "orchestrator"
    gate = _step(receipt, "orchestrator")
    assert "لم يُعثر على ملف قائم" in gate.details_ar
    assert "غير موجود على القرص" in gate.details_ar


def test_unknown_mode_raises_arabic() -> None:
    with pytest.raises(ValueError) as excinfo:
        AISession(mode="nope")
    assert "نمط جلسة غير معروف" in str(excinfo.value)


# ============================================================ الحتمية
def test_existing_dry_run_receipt_byte_deterministic(tmp_path: Path) -> None:
    target = _make_file(tmp_path)
    goal = _goal_with(target, GOAL_FIX)
    r1 = AISession(mode="existing").run(goal, tmp_path / "out", write=False)
    r2 = AISession(mode="existing").run(goal, tmp_path / "out", write=False)
    assert r1.to_json() == r2.to_json()


# ============================================================ الجلسة الافتراضية
def test_factory_mode_untouched_by_default(tmp_path: Path) -> None:
    """السلوك الافتراضي لم يتغير: factory يبني مشروعاً عبر بوابة التوليد."""
    receipt = AISession().run("قائمة مهام للفريق", tmp_path / "proj", write=False)
    assert receipt.ok, receipt.verdict_ar()
    names = [s.step for s in receipt.steps]
    assert "generate" in names
    assert "orchestrator" not in names


# ============================================================ CLI نهاية-إلى-نهاية
def test_cli_existing_mode_dry_run_json(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from zyko.cli import main

    target = _make_file(tmp_path)
    out = tmp_path / "cli-out"
    code = main(
        [
            "ai",
            "run",
            "--mode",
            "existing",
            "--goal",
            _goal_with(target, GOAL_FIX),
            "--out",
            str(out),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    steps = {s["step"] for s in payload["steps"]}
    assert "orchestrator" in steps
    assert "التصنيف FIX" in payload["steps"][1]["details_ar"]


def test_cli_invalid_mode_is_usage_error() -> None:

    from zyko.cli import main

    with pytest.raises(SystemExit):
        main(["ai", "run", "--mode", "galaxy", "--goal", "راجع x.py", "--out", "/tmp/x"])


def test_cli_mode_defaults_to_factory(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """بلا --mode يبقى كل شيء كما كان — الحمولة تحمل بوابة التوليد لا orchestrator."""
    from zyko.cli import main

    out = tmp_path / "proj"
    code = main(
        ["ai", "run", "--goal", "قائمة مهام", "--out", str(out), "--dry-run", "--format", "json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {s["step"] for s in payload["steps"]} >= {"plan", "generate"}
    assert "orchestrator" not in {s["step"] for s in payload["steps"]}
