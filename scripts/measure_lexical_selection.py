#!/usr/bin/env python3
"""measure_lexical_selection.py — عدّة الموجة 21: قيمة الخريطة الدلالية بلا نموذج.

على العينة الواسعة نفسها (44 حالة psf/requests، بيانات المستودع
``benchmarks/data/swe_bench_full_requests.json``) — لكل حالة:

1. شجرة عمل معزولة على الإيثاق الأساس (نفس بروتوكول المتسابق).
2. شجرة الاختيار ``repo_py_tree`` + خريطة repo-map v2 (توقيع الرموز).
3. المختار المعجمي الحتمي يرتّب الشجرة مرتين: بخريطة وبلا خريطة.
4. الإصابة تحكم على المسارات الذهبية (مسارات حصراً — لا محتوى رقعة).

الناتج وثيقة موقعة بسلسلة sha256 مثل كل وثائق العدّة — الأرقام كلها
حتمية بالبايت وتُعاد بأمر واحد. هذا حَدّ أدنى لمعلومات الخريطة
(مختار معجمي لا يفهم المعنى) — مرساة العقل الحقيقي 74.42% تُقارن
عليها نتيجة الموجة 22 لاحقاً.

الاستعمال:
    python3 scripts/measure_lexical_selection.py \
        --repo ~/.cache/zyko-swe/requests \
        --out benchmarks/results/lexmap_wide_2026-11-13.json
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 — أوامر بروتوكول ثابتة بمسارات معلنة
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zyko.benchmarks.lexical_chooser import (  # noqa: E402
    case_hit,
    precision_at_k,
    rank_files,
    summarize_hits,
)
from zyko.benchmarks.runner import (  # noqa: E402
    _ensure_repo,
    _sha16,
    atomic_write_json,
    chain_hash_of,
    load_instances,
    remove_worktree,
)
from zyko.benchmarks.selection import load_gold_paths  # noqa: E402
from zyko.benchmarks.swebench import repo_py_tree  # noqa: E402
from zyko.reviewer.repo_map import build_repo_map  # noqa: E402

DEFAULT_GOLD = Path("benchmarks/data/swe_bench_gold_paths.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measure_lexical_selection",
        description="قيمة الخريطة الدلالية على العينة الواسعة — مختار معجمي حتمي بلا نموذج",
    )
    parser.add_argument(
        "--repo", type=str, default=str(Path.home() / ".cache" / "zyko-swe" / "requests")
    )
    parser.add_argument("--data", type=str, default=None, help="افتراضي: بيانات العينة الواسعة")
    parser.add_argument("--gold", type=str, default=str(DEFAULT_GOLD))
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument("--max-files", type=int, default=400)
    args = parser.parse_args(argv)

    data_path = (
        Path(args.data)
        if args.data
        else Path(__file__).resolve().parent.parent / "benchmarks/data/swe_bench_full_requests.json"
    )
    repo_path = _ensure_repo(Path(args.repo))
    gold_map = load_gold_paths(Path(args.gold))
    instances = load_instances(data_path)
    state_dir = Path(args.out).resolve().parent.parent.parent / ".lexmap-trees"
    state_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for index, instance in enumerate(sorted(instances, key=lambda i: i.instance_id), start=1):
        gold = gold_map.get(instance.instance_id, ())
        workdir = state_dir / instance.instance_id
        record: dict[str, Any] = {
            "instance_id": instance.instance_id,
            "gold_paths": list(gold),
            "measured": False,
            "reason_ar": None,
        }
        proc = subprocess.run(  # nosec B603 B607 — أمر بروتوكول ثابت على إيثاق بالهاش
            ["git", "worktree", "add", "--detach", str(workdir), instance.base_commit],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            record["reason_ar"] = f"فشل شجرة العمل: {proc.stderr.strip()[-200:]}"
            records.append(record)
            print(
                f"[{index:02d}/{len(instances)}] {instance.instance_id} — شجرة فشلت",
                file=sys.stderr,
            )
            continue
        try:
            tree = repo_py_tree(workdir, subprocess.run)
            if not tree:
                record["reason_ar"] = "شجرة فارغة — لا ملفات مصدر"
                records.append(record)
                continue
            map_lines = build_repo_map(workdir, max_files=args.max_files)
            ranked_map = rank_files(
                instance.problem_statement, tree, map_lines, instance.fail_to_pass
            )
            ranked_none = rank_files(instance.problem_statement, tree, (), instance.fail_to_pass)
            record.update(
                {
                    "measured": True,
                    "tree_size": len(tree),
                    "map_lines": len(map_lines),
                    "top1_map": ranked_map[0],
                    "top1_no_map": ranked_none[0],
                    "hit_top1_map": case_hit(ranked_map, gold, 1),
                    "hit_top1_no_map": case_hit(ranked_none, gold, 1),
                    "hit_top3_map": case_hit(ranked_map, gold, 3),
                    "precision_top1_map": precision_at_k(ranked_map, gold, 1),
                }
            )
        finally:
            remove_worktree(repo_path, workdir, subprocess.run)
        records.append(record)
        mark = "إصابة" if record.get("hit_top1_map") else "سقوط"
        print(
            f"[{index:02d}/{len(instances)}] {instance.instance_id} — بخريطة: "
            f"{record.get('top1_map')} ({mark}) · بلا خريطة: {record.get('top1_no_map')}",
            file=sys.stderr,
        )

    summary = summarize_hits(records)
    # وثيقة بنفس مخطط وثائق العدّة — الخلاصة هنا خلاصة المختار المعجمي
    # لا خلاصة حلقة الإصلاح، فالتجميع مبني مباشرة لا عبر aggregate_loop_results
    doc: dict[str, Any] = {
        "protocol": "المختار المعجمي الحتمي — قيمة repo-map v2 (توقيع الرموز) على العينة الواسعة (الموجة 21)",
        "data": {
            "source": data_path.name,
            "instances_sha16": _sha16(data_path.read_text(encoding="utf-8")),
            "gold_sha16": _sha16(Path(args.gold).read_text(encoding="utf-8")),
        },
        "model_label": "lexical-chooser (بلا نموذج — حتمي بالبايت)",
        "model_served_by": "لا شيء — معجم وتقاطعات حصراً",
        "httpbin": "غير مستخدم",
        "python_env": sys.version.split()[0],
        "loop": {
            "weights": "مسار ×2 ورموز خريطة ×2 — الأزواج المتساوية تُفروز بالمسار",
            "comparison": "بخريطة v2 مقابل بلا خريطة (مسارات حصراً) — الإصابة على أول 1 و3",
            "note_ar": "حد أدنى لمعلومات الخريطة: مختار معجمي لا يفهم المعنى — مرساة العقل 74.42% تُقارن عليها الموجة 22",
        },
        "aggregate": summary,
        "results": records,
        "planned_total": len(instances),
    }
    doc["chain_hash"] = chain_hash_of(doc)
    atomic_write_json(Path(args.out), doc)
    print(f"الوثيقة: {args.out} — البصمة {doc['chain_hash']}", file=sys.stderr)
    print(
        f"الخلاصة: مقاسة {summary.get('measurable_cases')} · "
        f"بخريطة {summary.get('hit_top1_map')} · بلا خريطة {summary.get('hit_top1_no_map')} · "
        f"أول-3 بخريطة {summary.get('hit_top3_map')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
