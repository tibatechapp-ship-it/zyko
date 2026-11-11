"""اختبارات gauntlet_plus — طبقة الشدّ: حتمية متكررة × سرعة × مراجعة ذاتية.

العقد المُختبر:
1. المصفوفة تُبنى N مرة وبصمتها تتطابق بالبايت — والانزلاق المُصطنَع
   يُكشف فورًا (ok=False + مشكلة عربية صريحة).
2. حارس السرعة: ميزانية مستحيلة تكشف البطء؛ الأزمنة خارج الإيصال إلا
   مع include_timing — الإيصال الحتمي بلا أزمنة دائمًا.
3. المراجعة الذاتية: عتبة مستحيلة ترفض الكل، وعتبة سائحة تمرر الكل —
   وبصمة العينة قابلة لإعادة الحساب من صفوفها دون ثقة.
4. CLI: ``zyko gauntlet --repeats/--review-sample`` يفعّل طبقة الشدّ
   ويطبع جدولها العربي — والمسار القائم بلا هذه الأعلام يبقى كما هو.
"""

from __future__ import annotations

import hashlib

import pytest

from zyko.benchmarks.gauntlet import GauntletReport, build_matrix
from zyko.benchmarks.gauntlet_plus import (
    DEFAULT_REVIEW_MIN_SCORE,
    StressReport,
    run_stress_gauntlet,
)


# ------------------------------------------------------------- الاكتشاف الموقّع
def test_signed_threshold_is_seventy() -> None:
    """العتبة الموقّعة: 70 فوق الاكتشاف التاريخي (48) بهامش حقيقي."""
    assert DEFAULT_REVIEW_MIN_SCORE == 70


def test_generated_output_reviews_at_hundred() -> None:
    """مصفوفة كاملة (كل النوايا × نسخة) تُراجَع ملفاً ملفًا بدرجة 100."""
    from zyko.coder.generate import build_all_files
    from zyko.reviewer.engine import ReviewEngine

    engine = ReviewEngine()
    for plan in build_matrix(1):
        for path, item in sorted(build_all_files(plan).items()):
            if not path.endswith(".py"):
                continue
            result = engine.review_source(item.content, f"{plan.name}/{path}")
            assert result.score == 100, f"{plan.name}/{path}: {result.score}"
            assert result.findings == [], f"{plan.name}/{path}: {result.findings}"


def test_embedded_gauntlet_failure_blocks_ok() -> None:
    """فشل صادق: البناء والتنفيذ 96/100 داخل طبقة الشدّ يرفض ok الكلية."""
    rows = ()
    report = StressReport(
        per_intent=2,
        repeats=1,
        matrix_hashes=("a" * 64,),
        determinism_ok=True,
        build_stats=None,
        review_rows=rows,
        review_min_score=70,
    )
    assert report.ok
    broken = GauntletReport(per_intent=2, rows=(), executed=0)
    assert not broken.ok  # مصفوفة فارغة = فشل
    failed = StressReport(
        per_intent=2,
        repeats=1,
        matrix_hashes=("a" * 64,),
        determinism_ok=True,
        build_stats=None,
        review_rows=rows,
        review_min_score=70,
        gauntlet=broken,
    )
    assert not failed.ok, "الناتج يجب أن يعكس فشل الـ gauntlet المضمّن"


# ------------------------------------------------------------- القبول الكامل
def test_stress_ok_on_defaults() -> None:
    """مصفوفة صغيرة × بناء متكرر: كل الحراس خضراء والبصمات متطابقة."""
    report = run_stress_gauntlet(per_intent=2, repeats=3, review_sample=4)
    assert report.ok
    assert report.determinism_ok
    assert len(report.matrix_hashes) == 3
    assert len(set(report.matrix_hashes)) == 1
    assert report.build_stats is not None and report.build_stats.within_budget
    assert report.review_rows and all(row.ok for row in report.review_rows)
    assert report.problems == ()


# ------------------------------------------------------------- حارس الحتمية
def test_determinism_slip_is_caught(monkeypatch) -> None:
    """انزلاق مُصطنَع بين البناءات ⇒ ok=False ومشكلة عربية صريحة."""
    real_build = build_matrix
    calls = {"n": 0}

    def flaky(per_intent: int = 100):
        calls["n"] += 1
        plans = real_build(per_intent)
        if calls["n"] >= 2:  # البناء الثاني يتغير — مثل عشوائية حقيقية
            first = plans[0]
            plans[0] = type(first)(
                **{**first.__dict__, "description": first.description + " انزلاق"}
            )
        return plans

    monkeypatch.setattr("zyko.benchmarks.gauntlet_plus.build_matrix", flaky)
    report = run_stress_gauntlet(per_intent=1, repeats=2, review_sample=0)
    assert not report.determinism_ok
    assert not report.ok
    assert any("انزلاق" in p for p in report.problems)


# ------------------------------------------------------------- حارس السرعة
def test_speed_budget_exceeded_is_caught() -> None:
    """ميزانية مستحيلة (ميكروثانية) ⇒ الفشل صادق والمشكلة تذكر الميزانية."""
    report = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=0, speed_budget_ms=0.000001)
    assert report.build_stats is not None
    assert not report.build_stats.within_budget
    assert not report.ok
    assert any("الميزانية" in p for p in report.problems)


def test_timing_stays_out_of_deterministic_receipt() -> None:
    """الأزمنة خارج الإيصال الحتمي دائمًا — وتدخل فقط مع include_timing."""
    report = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=1)
    assert "build_stats" not in report.to_dict()
    assert "build_stats" in report.to_dict(include_timing=True)
    a = report.to_json()
    b = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=1).to_json()
    assert a == b  # الإيصال الحتمي متطابق بالبايت بين تشغيلين


# ------------------------------------------------------------- المراجعة الذاتية
def test_review_sample_deterministic_chain() -> None:
    """نفس المدخل ⇒ نفس بصمة عينة المراجعة بالبايت."""
    a = run_stress_gauntlet(per_intent=2, repeats=1, review_sample=5)
    b = run_stress_gauntlet(per_intent=2, repeats=1, review_sample=5)
    assert a.review_chain_hash == b.review_chain_hash
    assert [r.to_dict() for r in a.review_rows] == [r.to_dict() for r in b.review_rows]


def test_review_chain_hash_recomputable_from_rows() -> None:
    """البصمة تُعاد حسابها من الصفوف نفسها — تحقق دون ثقة (عقد zyko verify)."""
    report = run_stress_gauntlet(per_intent=2, repeats=1, review_sample=4)
    digest = hashlib.sha256()
    for row in report.review_rows:
        digest.update(f"{row.name}|{row.files}|{row.min_score}|{row.findings}".encode("utf-8"))
        digest.update(b"\x00")
    assert report.review_chain_hash == digest.hexdigest()


def test_impossible_review_threshold_rejects_all() -> None:
    """عتبة 101 ⇒ كل الصفوف فاشلة ومشكلة صريحة — لا اعتذار ولا إخفاء."""
    report = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=3, review_min_score=101)
    assert report.review_rows and all(not row.ok for row in report.review_rows)
    assert not report.ok
    assert any("عتبة المراجعة" in p for p in report.problems)


def test_lenient_review_threshold_accepts_all() -> None:
    """عتبة 0 ⇒ كل الصفوف ناجحة — العتبة نفسها هي القرار الحاسم."""
    report = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=3, review_min_score=0)
    assert all(row.ok for row in report.review_rows)
    assert report.ok


# ------------------------------------------------------------- الجدول والإخراج
def test_table_ar_shows_three_guards() -> None:
    report = run_stress_gauntlet(per_intent=1, repeats=2, review_sample=2)
    table = report.table_ar()
    assert "الحتمية المتكررة" in table and "حارس السرعة" in table and "المراجعة الذاتية" in table
    assert "كل الحراس خضراء" in table


def test_invalid_args_raise() -> None:
    with pytest.raises(ValueError):
        run_stress_gauntlet(per_intent=1, repeats=0)
    with pytest.raises(ValueError):
        run_stress_gauntlet(per_intent=1, review_sample=-1)


def test_execute_passthrough_embeds_gauntlet() -> None:
    """execute>0 يضمّن الفحص القائم في التقرير — نفس عقد run_gauntlet."""
    report = run_stress_gauntlet(per_intent=1, repeats=1, review_sample=1, execute=1)
    assert report.gauntlet is not None
    assert report.gauntlet.total == 10  # 10 نوايا × 1
    assert report.gauntlet.passed == report.gauntlet.total


# ------------------------------------------------------------- CLI
def test_cli_gauntlet_stress_path(tmp_path, capsys) -> None:
    """--repeats/--review-sample تفعّل طبقة الشدّ في CLI وتطبع جدولها."""
    from types import SimpleNamespace

    from zyko.cli.commands import cmd_gauntlet

    args = SimpleNamespace(
        per_intent=1,
        execute=0,
        execute_all=False,
        json_out=None,
        include_timing=False,
        repeats=2,
        review_sample=2,
    )
    code = cmd_gauntlet(args)
    out = capsys.readouterr().out
    assert code == 0
    assert "طبقة الشدّ" in out and "كل الحراس خضراء" in out


def test_cli_gauntlet_stress_json_out(tmp_path, capsys) -> None:
    from types import SimpleNamespace

    from zyko.cli.commands import cmd_gauntlet

    json_path = tmp_path / "stress.json"
    args = SimpleNamespace(
        per_intent=1,
        execute=0,
        execute_all=False,
        json_out=str(json_path),
        include_timing=False,
        repeats=1,
        review_sample=2,
    )
    code = cmd_gauntlet(args)
    assert code == 0
    assert json_path.is_file()
    assert "gauntlet_stress" in json_path.read_text(encoding="utf-8")


def test_cli_gauntlet_classic_path_unchanged(capsys) -> None:
    """بلا أعلام الشدّ: المسار القائم كما كان — جدول Gauntlet القديم."""
    from types import SimpleNamespace

    from zyko.cli.commands import cmd_gauntlet

    args = SimpleNamespace(
        per_intent=1,
        execute=0,
        execute_all=False,
        json_out=None,
        include_timing=False,
        repeats=1,
        review_sample=0,
    )
    code = cmd_gauntlet(args)
    out = capsys.readouterr().out
    assert code == 0
    assert "الفحص الكبير" in out  # جدول run_gauntlet القائم


def test_cli_execute_reaches_stress_layer(monkeypatch, tmp_path) -> None:
    """--execute لم يعد يسقط بصمت: يصل لطبقة الشدّ مع repeats/review معًا."""
    from zyko.cli.commands import cmd_gauntlet

    captured: dict[str, object] = {}

    def fake_stress(per_intent, *, repeats, review_sample, execute=0, **kw):
        captured.update(
            per_intent=per_intent, repeats=repeats, review_sample=review_sample, execute=execute
        )

        from zyko.benchmarks.gauntlet_plus import StressReport as R

        return R(
            per_intent=per_intent,
            repeats=repeats,
            matrix_hashes=("a" * 64,),
            determinism_ok=True,
            build_stats=None,
            review_rows=(),
            review_min_score=70,
        )

    monkeypatch.setattr("zyko.benchmarks.gauntlet_plus.run_stress_gauntlet", fake_stress)

    class Args:
        per_intent = 2
        execute = 5
        execute_all = False
        repeats = 2
        review_sample = 3
        json_out = str(tmp_path / "stress.json")
        include_timing = False

    assert cmd_gauntlet(Args()) == 0
    assert captured["execute"] == 5, "--execute يجب أن يصل لطبقة الشدّ"
    assert captured["repeats"] == 2 and captured["review_sample"] == 3
