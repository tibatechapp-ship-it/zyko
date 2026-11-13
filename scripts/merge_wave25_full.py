#!/usr/bin/env python3
"""merge_wave25_full.py — دمج الموجة 25: العينة الكاملة 44 من وثيقتين موقعتين.

درس عقد التنفّس (الموجة 23): وثيقة واحدة لكل حالة. التشغيلة 25 أعادت
تشغيل وفيات الاختيار الأربع والثلاثين حصراً — والاستحقاق أن يبقى
المقياس على العينة الكاملة نفسها (44) لا على مقطع. هذا الدمج ميكانيكي
حتمي: سجلات الموجة 22 التسعة الناجية تبقى كما هي ببصماتها، وسجلات
التشغيلة 25 تستبدل نظيراتها الميتة بـ ``merge_result`` (الأحدث يفوز)،
والخلاصة تُعاد من السجلات المدموجة لا من يد.

الاستخدام:
    PYTHONPATH=src python3 scripts/merge_wave25_full.py \
        --base benchmarks/results/swebench_full_wide22_2026-11-13.json \
        --delta benchmarks/results/swebench_full_wide25_2026-11-14.json \
        --out benchmarks/results/swebench_full_wide25_merged_2026-11-14.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zyko.benchmarks.runner import assemble_doc, atomic_write_json, chain_hash_of, merge_result
from zyko.benchmarks.selection import DEFAULT_GOLD_PATHS, load_gold_paths, selection_accuracy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="دمج وثيقتي الموجة 22/25 في عينة كاملة موقعة")
    parser.add_argument("--base", required=True, help="وثيقة الموجة 22 (44 سجلاً — تسعة تنجو)")
    parser.add_argument("--delta", required=True, help="وثيقة التشغيلة 25 (34 سجلاً معاد تشغيلها)")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD_PATHS))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    delta = json.loads(Path(args.delta).read_text(encoding="utf-8"))
    base_results = list(base.get("results", []))
    delta_results = list(delta.get("results", []))
    if not delta_results:
        print("وثيقة التشغيلة 25 بلا سجلات — لا شيء يُدمج", file=sys.stderr)
        return 2

    merged = list(base_results)
    replaced = 0
    for record in delta_results:
        merged, replaced_now = merge_result(merged, record)
        replaced += replaced_now

    gold_map = None
    if Path(args.gold).exists():
        gold_map = load_gold_paths(Path(args.gold))

    delta_loop = delta.get("loop", {})
    doc = assemble_doc(
        protocol=(
            "SWE-bench (psf/requests) — العينة الكاملة 44 بعد منقِذ المسار (الموجة 25): "
            "تسعة ناجون من وثيقة الموجة 22 كما هم ببصماتهم، و34 وفاة اختيار أعيد تشغيلها "
            "بعقل حقيقي فوق المنقذ الحتمي، والدمج ميكانيكي بالأحدث يفوز"
        ),
        data=delta.get("data", base.get("data", {})),
        model_label=delta.get("model_label", base.get("model_label", "glm-4.7")),
        model_served_by=delta.get("model_served_by", base.get("model_served_by", "")),
        httpbin=delta.get("httpbin", base.get("httpbin", "")),
        python_env=delta.get("python_env", base.get("python_env", "")),
        loop={
            **{k: v for k, v in delta_loop.items()},
            "merge": {
                "base_doc": Path(args.base).name,
                "delta_doc": Path(args.delta).name,
                "base_records": len(base_results),
                "delta_records": len(delta_results),
                "replaced_records": replaced,
                "final_total": len(merged),
            },
        },
        results=merged,
        planned_total=len(base_results) or len(merged),
    )
    doc["selection"] = selection_accuracy(merged, gold_map).to_dict()
    doc["chain_hash"] = chain_hash_of(doc)
    atomic_write_json(Path(args.out), doc)

    agg = doc.get("aggregate", {})
    print(
        "الدمج تم: "
        f"سجلات الموجة 22: {len(base_results)} | التشغيلة 25: {len(delta_results)} | "
        f"مُستبدلة: {replaced} | النهائي: {len(merged)}",
        file=sys.stderr,
    )
    print(
        "الخلاصة المدموجة: "
        f"مطبقة {agg.get('applied_count')} | صارم {agg.get('resolved_strict')} | "
        f"بيئي {agg.get('resolved_env')} | بصمة {doc['chain_hash']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
