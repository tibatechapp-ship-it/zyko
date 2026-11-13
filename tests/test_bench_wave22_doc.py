"""اختبارات الموجة 22 — وثائق العقل الحقيقي الموقعة تُحكَم لا تُعدَّل.

العقد: كل رقم في وثائق الموجة 22 (نقطة القياس والتشغيل الكامل الأول)
مرساة اختبار — أي تعديل للأرقام بلا إعادة تشغيل موثقة يُكسر البوابة.
التشغيل الخانق موثق بعناده: الخنق حقيقة معلنة لا عذر مُصاغ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "benchmarks/results/swebench_pilot22_2026-11-13.json"
RUN1 = ROOT / "benchmarks/results/swebench_full_wide22_2026-11-13.json"


def test_pilot_doc_numbers_are_anchored():
    """نقطة القياس (6 حالات بنقية كاملة): بيئي 1/6 ورقع كاملة 5 واختيار 3/6."""
    doc = json.loads(PILOT.read_text(encoding="utf-8"))
    agg = doc["aggregate"]
    assert agg["total"] == 6
    assert agg["resolved_env"] == 1
    assert agg["applied_count"] == 5
    assert doc["selection"]["hit_any"] == 3
    assert doc["selection"]["hit_rate"] == pytest.approx(0.5)
    assert doc["selection"]["mean_precision"] == pytest.approx(1.0)
    assert doc["chain_hash"] == "21a51f70393af529"


def test_pilot_1142_flip_is_documented():
    """الإخفاق الرائد 1142: اختيار الموجة 19 كان api.py والموجة 22 models.py."""
    w19 = json.loads(
        (ROOT / "benchmarks/results/swebench_full_wide_2026-11-13.json").read_text(encoding="utf-8")
    )
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    by19 = {r["instance_id"]: r for r in w19["results"]}
    p1142 = next(r for r in pilot["results"] if r["instance_id"] == "psf__requests-1142")
    assert "requests/api.py" in (by19["psf__requests-1142"]["loop"]["file_choices"])
    assert "requests/models.py" in (p1142["loop"]["file_choices"])
    gold_paths = ("requests/models.py",)
    assert any(c in gold_paths for c in p1142["loop"]["file_choices"])


def test_run1_throttled_numbers_are_anchored():
    """التشغيل الكامل الأول (الخانق): صارم 2 وبيئي 2 وانصراف 34 من 60 محاولة."""
    doc = json.loads(RUN1.read_text(encoding="utf-8"))
    agg = doc["aggregate"]
    assert agg["total"] == 44 and agg["planned_total"] == 44
    assert agg["resolved_strict"] == 2
    assert agg["resolved_env"] == 2
    assert agg["applied_count"] == 9
    assert agg["reverted_count"] == 6
    assert agg["partial_applies"] == 1
    assert doc["chain_hash"] == "2a8bf413045ba0c7"
    attempts = [a for r in doc["results"] for a in (r["loop"].get("attempts") or [])]
    assert len(attempts) == 60
    saraf = [a for a in attempts if (a.get("stop_reason_ar") or "").startswith("انصراف — لا ملف")]
    assert len(saraf) == 34  # الخنق مفصول عقدة عقدة لا مُجمَّل


def test_run1_strict_resolves_are_named():
    """الحلّان الصارمان بالاسم — أول حلّ صارم في تاريخ العينة الواسعة."""
    doc = json.loads(RUN1.read_text(encoding="utf-8"))
    strict = {
        r["instance_id"]
        for r in doc["results"]
        if (r["loop"].get("verdict") or {}).get("resolved_strict")
    }
    assert strict == {"psf__requests-1537", "psf__requests-1689"}
    # 1537 كان من إخفاقات الموجة 19 المسماة — صار حلاً صارماً
    w19 = json.loads(
        (ROOT / "benchmarks/results/swebench_full_wide_2026-11-13.json").read_text(encoding="utf-8")
    )
    from zyko.benchmarks.selection import load_gold_paths, selection_accuracy

    gold = load_gold_paths(ROOT / "benchmarks/data/swe_bench_gold_paths.json")
    assert "psf__requests-1537" in selection_accuracy(w19["results"], gold).misses


def test_run1_selection_on_measurable_is_anchored():
    """الدقة على القابل للقياس: 9/10 إصابة بدقة 1.0 — الخنق لا يُستحال نصراً.

    القابل للقياس 10 حالات حصراً — البقية بلا اختيار قابل للتحليل
    (خنق نقطة النموذج)، والرقم يُعلن على عينته لا على 44."""
    doc = json.loads(RUN1.read_text(encoding="utf-8"))
    from zyko.benchmarks.selection import load_gold_paths, selection_accuracy

    gold = load_gold_paths(ROOT / "benchmarks/data/swe_bench_gold_paths.json")
    rep = selection_accuracy(doc["results"], gold)
    assert rep.measured
    assert rep.cases_with_choice == 10
    assert rep.hit_any == 9
    assert rep.hit_rate == pytest.approx(0.9)
    assert rep.mean_precision == pytest.approx(1.0)
    assert rep.misses == ("psf__requests-1537",)
