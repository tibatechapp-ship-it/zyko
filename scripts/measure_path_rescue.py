#!/usr/bin/env python3
"""measure_path_rescue.py — مسطرة منقِذ المسار بلا نموذج وبلا شبكة (الموجة 25).

درس الموجة 22 بالبايت: 34 حالة من 44 ماتت عند «اختيار الملف رُفض ببوابة
أو لم يعطِ مساراً موجوداً» — نقطة الفشل الأحادية للحلقة. هذه المسطرة
تقيس على العينة الواسعة نفسها **سقف المنقذ الحتمي**: ماذا كان سيحدث
لو عمل المنقذ بلا عقل أصلاً — مقارنة مباشرة بالمسارات الذهبية من ملف
المسطرة الموثق (المسارات حصراً بلا محتوى، ولا تصل للعقل أبداً).

المقاييس المعلنة:
- ``hit1``: المسار الأعلى في المسارات الذهبية — وضع «lexical» حصراً.
- ``hit3``: ذهبية ضمن أعلى 3 — عمق الطابور لمرحلة التالية.
- ``mean_gold_rank``: متوسط رتبة أول ذهبية (1.0 = إصابة تامة).

الاستخدام:
    PYTHONPATH=src python3 scripts/measure_path_rescue.py \
        --doc benchmarks/results/swebench_full_wide22_2026-11-13.json \
        --out benchmarks/results/path_rescue_2026-11-14.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from zyko.benchmarks.lexical_chooser import rank_files
from zyko.benchmarks.runner import (
    _ensure_repo,
    atomic_write_json,
    chain_hash_of,
    prepare_worktree,
    remove_worktree,
)
from zyko.benchmarks.selection import DEFAULT_GOLD_PATHS, load_gold_paths
from zyko.benchmarks.swebench import load_instances, repo_py_tree
from zyko.reviewer.repo_map import build_repo_map

_CHOICE_DEAD_AR = "اختيار الملف رُفض ببوابة أو لم يعطِ مساراً موجوداً"


def dead_cohort(doc: dict) -> tuple[str, ...]:
    """معرفات الحالات التي ماتت عند مرحلة الاختيار — من الوثيقة الموقعة."""
    dead: list[str] = []
    for record in doc.get("results", []):
        loop = record.get("loop") or {}
        verdict = loop.get("verdict") or {}
        if verdict.get("patch_applied"):
            continue
        attempts = loop.get("attempts") or []
        if attempts and attempts[-1].get("contract_reason_ar") == _CHOICE_DEAD_AR:
            dead.append(record["instance_id"])
    return tuple(sorted(dead))


def measure_case(instance, repo_path: Path, state_dir: Path) -> dict:
    """قَس حالة واحدة مرة واحدة: شجرة حية من الإيثاق ← ترتيب معجمي حتى 20."""
    workdir = state_dir / "rescue-worktrees" / instance.instance_id
    ok, reason = prepare_worktree(
        repo_path, instance.base_commit, workdir, instance.test_patch, subprocess.run
    )
    if not ok:
        return {"instance_id": instance.instance_id, "error_ar": reason}
    try:
        tree = repo_py_tree(workdir, subprocess.run)
        map_lines = tuple(build_repo_map(workdir))
        ranked = rank_files(
            instance.problem_statement,
            tree,
            map_lines=map_lines,
            fail_to_pass=tuple(instance.fail_to_pass),
        )
        return {
            "instance_id": instance.instance_id,
            "tree_size": len(tree),
            "top": ranked[0] if ranked else None,
            "top3": list(ranked[:3]),
            "top20": list(ranked[:20]),
        }
    finally:
        remove_worktree(repo_path, workdir, subprocess.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="مسطرة منقِذ المسار — بلا نموذج وبلا شبكة")
    parser.add_argument("--doc", required=True, help="وثيقة الموجة الموقعة لاستخراج وفيات الاختيار")
    parser.add_argument("--data", default="benchmarks/data/swe_bench_full_requests.json")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD_PATHS))
    parser.add_argument(
        "--repo", default=str(Path.home() / ".cache" / "zyko-swe" / "requests")
    )
    parser.add_argument(
        "--state-dir", default=str(Path.home() / ".cache" / "zyko-swe" / "state")
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    dead = dead_cohort(doc)
    if not dead:
        print("لا وفيات اختيار في الوثيقة — لا شيء يُقاس", file=sys.stderr)
        return 2
    instances = {i.instance_id: i for i in load_instances(Path(args.data))}
    missing = [d for d in dead if d not in instances]
    if missing:
        print(f"وفيات ليست في ملف البيانات: {missing[:3]}", file=sys.stderr)
        return 2
    gold_map = load_gold_paths(Path(args.gold))
    repo_path = _ensure_repo(Path(args.repo))
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for n, instance_id in enumerate(dead, start=1):
        inst = instances[instance_id]
        row = measure_case(inst, repo_path, state_dir)
        gold = gold_map.get(instance_id, ())
        top = row.get("top")
        top3 = row.get("top3") or []
        row["gold_paths"] = list(gold)
        top20 = row.get("top20") or []
        row["hit1"] = bool(top in gold) if top else False
        row["hit3"] = any(p in gold for p in top3)
        gold_ranks = [i + 1 for i, p in enumerate(top20) if p in gold]
        row["gold_rank_best"] = min(gold_ranks) if gold_ranks else None
        rows.append(row)
        mark = "إصابة" if row["hit1"] else ("ضمن3" if row["hit3"] else "فوات")
        print(f"[{n}/{len(dead)}] {instance_id}: {mark} — {top}", file=sys.stderr)

    hits1 = sum(1 for r in rows if r.get("hit1"))
    hits3 = sum(1 for r in rows if r.get("hit3"))
    ranks = [r["gold_rank_best"] for r in rows if r.get("gold_rank_best")]
    doc_out = {
        "protocol": "مسطرة منقِذ المسار الحتمي — بلا نموذج وبلا شبكة (الموجة 25)",
        "source_doc": Path(args.doc).name,
        "cohort": "وفيات مرحلة الاختيار حصراً",
        "total_dead": len(dead),
        "measured": len([r for r in rows if r.get("top") is not None or r.get("error_ar")]),
        "hit1": hits1,
        "hit1_rate": round(100.0 * hits1 / len(dead), 2) if dead else 0.0,
        "hit3": hits3,
        "hit3_rate": round(100.0 * hits3 / len(dead), 2) if dead else 0.0,
        "mean_gold_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "rows": rows,
    }
    doc_out["chain_hash"] = chain_hash_of(doc_out)
    atomic_write_json(Path(args.out), doc_out)
    print(
        f"الإيصال: {args.out} — إصابة تامة {hits1}/{len(dead)} ({doc_out['hit1_rate']}%) بلا أي عقل",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
