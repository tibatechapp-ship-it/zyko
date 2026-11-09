"""اختبارات إيصال جلسة الذكاء: سلسلة أدلة حتمية بالبايت موقّعة بالبصمات."""

from __future__ import annotations

import json

from zyko.ai.receipt import AIReceipt, StepRecord, hash_file, hash_text

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"


# ------------------------------------------------------------- البصمات
def test_hash_text_is_stable_and_hex() -> None:
    assert hash_text("abc") == hash_text("abc")
    assert hash_text("abc") != hash_text("abd")
    assert len(hash_text("سطر عربي")) == 64


def test_hash_file_matches_hash_text_for_same_bytes(tmp_path: object) -> None:
    p = tmp_path / "f.txt"  # type: ignore[attr-defined]
    p.write_text("محتوى عربي", encoding="utf-8")
    assert hash_file(p) == hash_text("محتوى عربي")


# ------------------------------------------------------------- الخطوات والحكم
def _ok_step() -> StepRecord:
    return StepRecord(step="plan", title_ar="بوابة الخطة", ok=True, exit_code=0, details_ar="نظيف")


def _fail_step(step: str = "plan") -> StepRecord:
    return StepRecord(step=step, title_ar="بوابة", ok=False, exit_code=1, details_ar="مرفوض")


def _receipt() -> AIReceipt:
    return AIReceipt(
        goal=CLEAN_GOAL,
        brain="gated:planner",
        brain_deterministic=True,
        out="proj",
    )


def test_add_first_failure_sets_failed_step_and_verdict() -> None:
    r = _receipt()
    r.add(_ok_step())
    assert r.ok and r.failed_step is None
    r.add(_fail_step("generate"))
    assert not r.ok and r.failed_step == "generate"
    assert "مرفوضة" in r.verdict_ar() and "generate" in r.verdict_ar()


def test_verdict_accepted_wording() -> None:
    r = _receipt()
    r.add(_ok_step())
    assert "مقبولة" in r.verdict_ar() and "✅" in r.verdict_ar()


# ------------------------------------------------------------- الحتمية
def test_to_dict_keys_are_stable() -> None:
    keys = list(_receipt().to_dict())
    assert keys[0] == "schema" and keys[1] == "zyko_version" and "steps" in keys


def test_to_json_is_byte_deterministic() -> None:
    r = _receipt()
    r.add(_ok_step())
    assert r.to_json() == r.to_json()
    parsed = json.loads(r.to_json())
    assert parsed["schema"] == "zyko.ai.receipt/v1"
    assert parsed["mode"] == "ai_session"
    assert parsed["goal"] == CLEAN_GOAL


def test_to_json_excludes_timing_by_default_includes_on_demand() -> None:
    r = _receipt()
    r.add(_ok_step())
    assert "seconds_total" not in r.to_json()
    assert "seconds_total" in r.to_json(include_timing=True)


def test_evidence_dict_is_sorted_in_step_payload() -> None:
    r = _receipt()
    r.add(
        StepRecord(
            step="generate",
            title_ar="توليد",
            ok=True,
            exit_code=0,
            evidence={"z.py": "h2", "a.py": "h1"},
        )
    )
    step = json.loads(r.to_json())["steps"][0]
    assert list(step["evidence"]) == ["a.py", "z.py"]


# ------------------------------------------------------------- الإيصال المقروء
def test_to_md_contains_receipt_sections() -> None:
    r = _receipt()
    r.add(_ok_step())
    md = r.to_md()
    assert md.startswith("# إيصال جلسة zyko AI")
    assert "| الخطوة | الحكم | رمز الخروج | الدليل |" in md
    assert "## البصمات (sha256)" not in md  # لا بصمات في هذا الإيصال


def test_to_md_lists_evidence_hashes() -> None:
    r = _receipt()
    r.add(
        StepRecord(
            step="generate",
            title_ar="توليد",
            ok=True,
            exit_code=0,
            evidence={"src/x.py": "ab" * 32},
        )
    )
    md = r.to_md()
    assert "`src/x.py` — " + "ab" * 32 in md
