"""اختبارات بوابة المرحلة 2 نفسها: البوابات الست وسلامة المرساة."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from zyko.reviewer import RULES, RULES_BY_ID
from zyko.reviewer.gate import (
    DETECT_WINDOW,
    default_samples_dir,
    run_phase2_gate,
)

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples" / "review"


def test_gate_all_six_pass_on_anchor_samples():
    gate = run_phase2_gate(SAMPLES)
    assert gate.ok, gate.table_ar()
    assert [r.gate_id for r in gate.rows] == ["G1", "G2", "G3", "G4", "G5", "G6"]
    assert gate.passed_count == 6


def test_gate_table_ar_summary():
    table = run_phase2_gate(SAMPLES).table_ar()
    assert "البوابة | الاسم | الحكم | التفصيل" in table
    assert "الخلاصة: 6/6 بوابات — الحكم: مقبول" in table


def test_gate_missing_samples_reports_g0(tmp_path):
    gate = run_phase2_gate(tmp_path)
    assert not gate.ok
    assert gate.rows[0].gate_id == "G0"
    assert "manifest" in gate.rows[0].detail_ar


def test_gate_default_samples_dir_from_repo_root(monkeypatch):
    monkeypatch.chdir(REPO)
    assert default_samples_dir() == SAMPLES


def test_gate_loose_recall_still_strict_enough():
    gate = run_phase2_gate(SAMPLES, min_recall=0.99)
    assert gate.rows[0].passed


def test_gate_detects_when_a_rule_is_removed():
    """بوابة G6 يجب أن تفشل فعليًا إذا عميت قاعدة — البوابة تختبر نفسها."""
    import zyko.reviewer.engine as engine_mod
    import zyko.reviewer.gate as gate_mod

    reduced = tuple(r for r in RULES if r.rule_id != "R-SEC-101")
    original = gate_mod.ReviewEngine
    gate_mod.ReviewEngine = lambda: engine_mod.ReviewEngine(rules=reduced)
    try:
        gate = run_phase2_gate(SAMPLES)
    finally:
        gate_mod.ReviewEngine = original
    g6 = next(r for r in gate.rows if r.gate_id == "G6")
    assert not g6.passed
    assert "R-SEC-101" in g6.detail_ar
    assert not gate.ok


def test_manifest_files_exist_and_rules_known():
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["clean"]) == 2
    total_planted = 0
    for entry in manifest["defective"]:
        assert (SAMPLES / entry["file"]).is_file()
        ids = [p["id"] for p in entry["planted"]]
        assert len(ids) == len(set(ids))
        for planted in entry["planted"]:
            assert planted["rule"] in RULES_BY_ID, planted
            total_planted += 1
    assert total_planted == 40


def test_manifest_planted_lines_inside_files():
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["defective"]:
        line_count = len((SAMPLES / entry["file"]).read_text(encoding="utf-8").splitlines())
        for planted in entry["planted"]:
            assert 1 <= planted["line"] <= line_count, (entry["file"], planted)


def test_gate_rule_coverage_matches_registry():
    gate = run_phase2_gate(SAMPLES)
    g6 = next(r for r in gate.rows if r.gate_id == "G6")
    assert g6.passed
    assert f"{len(RULES)}/{len(RULES)}" in g6.detail_ar


def test_detection_window_is_two_lines():
    assert DETECT_WINDOW == 2


def test_full_copy_of_samples_survives_copying(tmp_path):
    """البوابة تعمل من نسخة منقولة (تأكيد لا اعتماد على مواضع مطلقة)."""
    copied = tmp_path / "review"
    shutil.copytree(SAMPLES, copied)
    gate = run_phase2_gate(copied)
    assert gate.ok, gate.table_ar()
