"""اختبارات مسطرة دقة اختيار الملف (الموجة 20) — القياس بعد الجولة حصراً.

درس العينة الواسعة: 43/44 اختار العقل ملفاً حقيقياً والدقة لم تُقَس.
هذه الاختبارات تحكم: الحساب نفسه، الصمت الصادق بلا ذهبية، عقد ملف
المسارات (مسارات حصراً بلا محتوى رقعة)، والرقم المقاس على الوثيقة
الموثقة للموجة 19 — مرساة لا تتغير باختيار سطرها.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.benchmarks.runner import aggregate_loop_results
from zyko.benchmarks.selection import load_gold_paths, selection_accuracy
from zyko.benchmarks.swebench import load_instances

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "benchmarks" / "data" / "swe_bench_gold_paths.json"
FULL = ROOT / "benchmarks" / "data" / "swe_bench_full_requests.json"
WIDE_DOC = ROOT / "benchmarks" / "results" / "swebench_full_wide_2026-11-13.json"


def _result(instance_id: str, choices: list[str | None]) -> dict:
    return {"instance_id": instance_id, "loop": {"file_choices": choices}}


# --------------------------------------------------------------- الحساب
def test_selection_accuracy_measures_hits_precision_and_misses():
    results = [
        _result("a", ["x.py", "y.py"]),
        _result("b", ["z.py", None]),
        _result("c", []),  # بلا اختيار — يُستثنى معلناً
        _result("d", ["q.py"]),
    ]
    gold = {"a": ("x.py",), "b": ("z.py",), "c": ("w.py",), "d": ("real.py",)}
    rep = selection_accuracy(results, gold)
    assert rep.measured
    assert rep.cases_with_choice == 3
    assert rep.cases_with_gold == 4
    assert rep.hit_any == 2
    assert rep.hit_rate == pytest.approx(2 / 3)
    assert rep.mean_precision == pytest.approx((0.5 + 1.0) / 2)
    assert rep.misses == ("d",)


def test_selection_without_gold_is_honestly_unmeasured():
    rep = selection_accuracy([_result("a", ["x.py"])], None)
    assert not rep.measured
    assert "غير مقاسة" in rep.reason_ar
    assert rep.to_dict()["measured"] is False


def test_selection_empty_gold_map_is_unmeasured_too():
    rep = selection_accuracy([_result("a", ["x.py"])], {})
    assert not rep.measured


def test_selection_report_has_no_timestamps():
    doc = selection_accuracy([_result("a", ["x.py"])], {"a": ("x.py",)}).to_dict()
    assert not any("time" in k or "date" in k for k in doc)


# --------------------------------------------------------------- عقد الملف
def test_gold_paths_file_is_paths_only_and_covers_wide_data():
    """المسارات الذهبية موثقة لكل الحالات الـ44، ومحتوى الرقعة غير موجود
    في الملف أصلاً — عقد الموجة 19 (المقياس هو zyko لا الوحش)."""
    gold = load_gold_paths(GOLD)
    instances = load_instances(FULL)
    assert set(gold) == {i.instance_id for i in instances}
    assert len(gold) == 44
    text = GOLD.read_text(encoding="utf-8")
    assert "diff --git" not in text and "@@" not in text
    for paths in gold.values():
        assert paths
        assert all(p.startswith("requests/") for p in paths)


def test_load_gold_paths_rejects_corrupt_values(tmp_path):
    bad = tmp_path / "g.json"
    bad.write_text(json.dumps({"instances": {"a": "x.py"}}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gold_paths(bad)


def test_load_gold_paths_dedupes_and_sorts():
    gold = load_gold_paths(GOLD)
    assert all(list(paths) == sorted(set(paths)) for paths in gold.values())


# --------------------------------------------------------------- المراساة
def test_selection_accuracy_on_tracked_wide_doc_is_anchored():
    """الرقم المقاس على وثيقة الموجة 19 الموثقة (بصمة bf10821c4eaa2ecf):
    43 حالة لها اختيار، 32 أصابت مساراً ذهبياً (74.42%)، ومتوسط الدقة
    93.75% — مرساة قياس تُقارن عليها كل جولة قادمة."""
    doc = json.loads(WIDE_DOC.read_text(encoding="utf-8"))
    gold = load_gold_paths(GOLD)
    rep = selection_accuracy(doc["results"], gold)
    assert rep.measured
    assert rep.cases_with_choice == 43
    assert rep.cases_with_gold == 44
    assert rep.hit_any == 32
    assert rep.hit_rate == pytest.approx(0.7442, abs=1e-3)
    assert rep.mean_precision == pytest.approx(0.9375, abs=1e-3)
    assert len(rep.misses) == 11
    assert "psf__requests-1142" in rep.misses  # api.py اختير والذهبية models.py


# --------------------------------------------------------------- الخلاصة
def test_aggregate_counts_reverted_and_partial_applies():
    verdict = {
        "resolved_strict": False,
        "resolved_env": False,
        "f2p_repaired_count": 0,
        "f2p_failed_at_base": ["t::f"],
        "f2p_failed_after": ["t::f"],
        "f2p_passed_after": [],
        "patch_applied": True,
    }
    record = {
        "instance_id": "a",
        "loop": {
            "verdict": verdict,
            "attempts": [
                {
                    "applied": True,
                    "apply_mode": "كاملة",
                    "reverted": True,
                    "contract_reason_ar": "مسموح",
                    "accepted": True,
                },
                {
                    "applied": True,
                    "apply_mode": "بالأجزاء",
                    "reverted": False,
                    "contract_reason_ar": "مسموح",
                    "accepted": True,
                },
            ],
        },
    }
    agg = aggregate_loop_results([record])
    assert agg["reverted_count"] == 1
    assert agg["partial_applies"] == 1
    assert agg["applied_count"] == 1
    # سجلات الموجة 19 القديمة بلا مفاتيح الجدة — الصمت يعني صفر لا انهيار
    old_record = {
        "instance_id": "b",
        "loop": {
            "verdict": verdict,
            "attempts": [{"applied": True, "contract_reason_ar": "مسموح", "accepted": True}],
        },
    }
    agg_old = aggregate_loop_results([old_record])
    assert agg_old["reverted_count"] == 0 and agg_old["partial_applies"] == 0
