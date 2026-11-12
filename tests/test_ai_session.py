"""اختبارات جلسة الذكاء الموثّقة: هدف عربي ⇒ مشروع عبر بوابات المصنع."""

from __future__ import annotations

import json
from pathlib import Path

from zyko.ai.brains import GatedBrain, PlannerBrain
from zyko.ai.session import DEFAULT_FAIL_UNDER, AISession

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"
PII_GOAL = "قائمة مهام — للتنسيق اتصل على 0501234567"


# ------------------------------------------------------------- الجلسة الكاملة
def test_full_session_accepted_with_receipt_files(tmp_path: Path) -> None:
    session = AISession(rounds=1)
    receipt = session.run(CLEAN_GOAL, tmp_path / "proj", write=True)
    assert receipt.ok, receipt.to_md()
    assert [s.step for s in receipt.steps] == [
        "mode",
        "plan",
        "generate",
        "baseline_update",
        "baseline_check",
    ]
    out = tmp_path / "proj"
    assert (out / ".zyko" / "ai_receipt.json").is_file()
    assert (out / ".zyko" / "AI_RECEIPT.md").is_file()
    assert (out / ".zyko" / "baseline.json").is_file()
    assert receipt.min_score_after >= DEFAULT_FAIL_UNDER


def test_written_receipt_matches_in_memory_receipt(tmp_path: Path) -> None:
    session = AISession()
    receipt = session.run(CLEAN_GOAL, tmp_path / "proj", write=True)
    on_disk = (tmp_path / "proj" / ".zyko" / "ai_receipt.json").read_text(encoding="utf-8")
    assert on_disk == receipt.to_json()


def test_session_evidence_hashes_point_to_real_files(tmp_path: Path) -> None:
    from zyko.ai.receipt import hash_file

    session = AISession()
    receipt = session.run(CLEAN_GOAL, tmp_path / "proj", write=True)
    gen = next(s for s in receipt.steps if s.step == "generate")
    assert gen.evidence
    for rel, digest in gen.evidence.items():
        assert (tmp_path / "proj" / rel).is_file()
        assert hash_file(tmp_path / "proj" / rel) == digest


def test_write_receipt_creates_zyko_dir(tmp_path: Path) -> None:
    session = AISession()
    receipt = session.run(CLEAN_GOAL, tmp_path / "p", write=False)
    written = session.write_receipt(receipt, tmp_path / "fresh")
    assert all(Path(w).is_file() for w in written)


# ------------------------------------------------------------- بوابة الخطة
def test_pii_goal_rejected_at_plan_gate_and_nothing_written(tmp_path: Path) -> None:
    out = tmp_path / "suspicious"
    receipt = AISession().run(PII_GOAL, out, write=True)
    assert not receipt.ok
    assert receipt.failed_step == "plan"
    assert not out.exists()  # لا توليد بعد الرفض — لا بايت على القرص
    plan = next(s for s in receipt.steps if s.step == "plan")
    assert plan.exit_code == 1


def test_dry_run_skips_baseline_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "dry"
    receipt = AISession().run(CLEAN_GOAL, out, write=False)
    assert not out.exists()
    assert receipt.dry_run is True
    assert receipt.ok  # الحلقة اكتملت في الذاكرة والبوابات خضراء
    assert receipt.files_written == []  # لا بايت على القرص
    # في التشغيل الجاف تُسجَّل خطوات خط الأساس كتخطٍّ:
    assert any(s.step == "baseline_update" and "جاف" in s.details_ar for s in receipt.steps)


# ------------------------------------------------------------- الحروس الهيكلية
def test_empty_goal_structural_exit2(tmp_path: Path) -> None:
    receipt = AISession().run("   ", tmp_path / "x", write=True)
    assert not receipt.ok and receipt.failed_step == "goal"
    step = receipt.steps[0]
    assert step.exit_code == 2


def test_non_string_goal_structural_exit2(tmp_path: Path) -> None:
    receipt = AISession().run(12345, tmp_path / "x", write=True)  # type: ignore[arg-type]
    assert not receipt.ok and receipt.failed_step == "goal"


def test_too_long_goal_structural_exit2(tmp_path: Path) -> None:
    receipt = AISession().run("وصف" * 3000, tmp_path / "x", write=True)
    assert not receipt.ok and receipt.failed_step == "goal"


def test_busy_out_dir_refused_without_touching_content(tmp_path: Path) -> None:
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("محتوى قديم", encoding="utf-8")
    receipt = AISession().run(CLEAN_GOAL, busy, write=True)
    assert not receipt.ok and receipt.failed_step == "out"
    assert (busy / "keep.txt").read_text(encoding="utf-8") == "محتوى قديم"


# ------------------------------------------------------------- الحتمية
def test_two_sessions_same_goal_byte_identical_receipts(tmp_path: Path) -> None:
    a = AISession().run(CLEAN_GOAL, tmp_path / "a", write=True)
    b = AISession().run(CLEAN_GOAL, tmp_path / "b", write=True)
    da, db = json.loads(a.to_json()), json.loads(b.to_json())
    da["out"] = db["out"] = "X"
    assert json.dumps(da, ensure_ascii=False, sort_keys=True) == json.dumps(
        db, ensure_ascii=False, sort_keys=True
    )


def test_custom_brain_and_threshold_are_recorded(tmp_path: Path) -> None:
    session = AISession(GatedBrain(PlannerBrain()), fail_under=10)
    receipt = session.run(CLEAN_GOAL, tmp_path / "p", write=False)
    payload = json.loads(receipt.to_json())
    assert payload["brain"] == "gated:planner"
    assert payload["fail_under"] == 10
