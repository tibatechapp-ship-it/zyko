"""اختبارات السجل المعياري المرجعي — benchmark ledger لا يتعفّت ولا يكذب.

العقود:
1. الغلاف الملتزم (benchmarks/results/baseline_2026-11-11.json) مكتمل
   الإثبات: إصدار متزامن مع الحزمة المثبتة، بصمة هدف sha256 صالحة،
   وإيصالا compare وgauntlet_stress أخضران بعقودهما البايتية.
2. القدرة المقاسة تُشتق حيًّا الآن على ملف حقيقي ملتزم بالمستودع —
   السجل يوثق تشغيلًا سابقًا، وهذا الاختبار يثبت أن القدرة نفسها
   قائمة اليوم (لا JSON أثريًا).
3. أي رقم مفبرك (دقة أقل من 1.0، حتمية زائفة، عتبة مراجعة تحت 70)
   يرفض صادقًا.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from zyko.version import __version__

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "benchmarks" / "results" / "baseline_2026-11-11.json"
REAL_FILE = ROOT / "src" / "zyko" / "reviewer" / "astcache.py"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load() -> dict:
    assert LEDGER.is_file(), f"السجل المرجعي مفقود: {LEDGER}"
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_ledger_envelope_provenance_is_coherent() -> None:
    d = _load()
    rec = d["recorded"]
    assert rec["zyko_version"] == __version__, (
        "السجل يوثق إصدارًا غير الإصدار المثبت — أعد التوليد بـ "
        "scripts/make_bench_baseline.py بعد أي bump"
    )
    assert rec["python"] and rec["platform"] and rec["date"]
    tgt = d["target"]
    assert SHA256_RE.match(tgt["sha256"]), "بصمة الهدف ليست sha256 سداسي عشري كامل"
    assert tgt["bytes"] > 0 and tgt["lines"] > 0
    assert "psf/requests" in tgt["label"], "الملصق يوثق مصدر الهدف الحقيقي"


def test_ledger_compare_receipt_contract() -> None:
    d = _load()
    c = d["compare"]
    assert c["kind"] == "compare" and c["ok"] is True
    assert c["accuracy"] == 1.0 and c["probes_passed"] == c["probes_total"]
    assert c["determinism_ok"] is True and c["verify_ok"] is True
    assert c["problems"] == []
    # جانب المنافس موثق بصدق: لم يُشغَّل ⇒ لا رقم مفبرك
    assert c["competitor"]["ran"] is False


def test_ledger_gauntlet_stress_contract() -> None:
    d = _load()
    g = d["gauntlet_stress"]
    assert g["kind"] == "gauntlet_stress" and g["ok"] is True
    assert g["determinism_ok"] is True
    assert g["repeats"] >= 2, "طبقة الشدّ تتطلب تكرارًا ≥2 بالبناء"
    assert g["review_min_score"] >= 70, "عتبة الاكتشاف الموقّع هي 70 — أقل منها إنكار للعقد"
    assert g["review_chain_hash"], "بصمة عينة المراجعة إلزامية"


def test_compare_capability_rederives_live_today() -> None:
    """القدرة نفسها تُشتق الآن على ملف حقيقي ملتزم — لا JSON أثريًا."""
    from zyko.benchmarks.compare import run_compare

    assert REAL_FILE.is_file(), f"الملف الحقيقي للإشتقاق مفقود: {REAL_FILE}"
    report = run_compare(str(REAL_FILE), runs=2)
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["accuracy"] == 1.0
    assert payload["determinism_ok"] is True
    assert payload["verify_ok"] is True
    # الحتمية البايتية للإيصال المشتق الحي: نفس الاستدعاء ⇒ نفس الأثر
    again = run_compare(str(REAL_FILE), runs=2).to_dict()
    assert payload == again
