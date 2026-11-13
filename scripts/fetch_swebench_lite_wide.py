#!/usr/bin/env python3
"""fetch_swebench_lite_wide.py — توسيع عينات SWE-bench من 6 حالات نحو 44 (الالموجة 19).

الفجوة الثانية الموثقة (docs/EVAL_2026-11-12.md §7.1): «التوسع من 6 حالات
إلى عينات أوسع هو الجولة القادمة». الجولة 8 أخذت ست حالات من
``princeton-nlp/SWE-bench_Lite`` — وتبين بالقياس أن Lite لا يضم غيرها من
psf/requests (المجموعة كاملة عنده ستة). التوسع الصادق إذن إلى **الأب
المباشر** للمقياس: ``princeton-nlp/SWE-bench`` الكامل (انقسام test عبر HF
datasets-server) بنفس المرشح ``psf/requests`` — نفس العائلة، نفس المستودع،
نفس بروتوكول البيئة، 44 حالة بدل 6. الرقعة الذهبية مستبعدة عمداً كما في
الجولة 8: المقياس هو zyko لا الوحش.

الاستخدام:
    python3 scripts/fetch_swebench_lite_wide.py --out benchmarks/data/swe_bench_full_requests.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "princeton-nlp/SWE-bench"
SPLIT = "test"
PAGE = 100
REPO_FILTER = "psf/requests"
FETCH_DATE = "2026-11-13"

FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "version",
    "problem_statement",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
)


def fetch_page(offset: int, *, retries: int = 5) -> dict:
    """صفحة واحدة من datasets-server — إعادة محاولة موثقة على 5xx/انقطاع."""
    url = "https://datasets-server.huggingface.co/rows?" + urllib.parse.urlencode(
        {
            "dataset": DATASET,
            "config": "default",
            "split": SPLIT,
            "offset": offset,
            "length": PAGE,
        }
    )
    last_error = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": f"zyko-swe/0.42 ({FETCH_DATE})"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            wait = 3.0 * attempt
            print(f"  [offset {offset}] محاولة {attempt} فشلت: {exc} — انتظار {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"تعذّر جلب الصفحة offset={offset} بعد {retries} محاولات: {last_error}")


def fetch_all_requests() -> list[dict]:
    """كل صفوف psf/requests عبر الترقيم الكامل — ترتيب المصدر يحفظ نفسه."""
    first = fetch_page(0)
    total = int(first["num_rows_total"])
    print(f"num_rows_total={total}", file=sys.stderr)
    rows: list[dict] = []
    offset = 0
    while offset < total:
        page = fetch_page(offset) if offset else first
        for row in page["rows"]:
            item = row["row"]
            if item.get("repo") == REPO_FILTER:
                rows.append({k: item.get(k) for k in FIELDS})
        offset += PAGE
        print(f"  offset {offset}/{total} — المجموع حتى الآن: {len(rows)}", file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="مسار ملف البيانات الواسع الناتج")
    args = ap.parse_args()

    rows = fetch_all_requests()
    if not rows:
        print("لا صفوف psf/requests — رفض الكتابة", file=sys.stderr)
        return 1
    ids = sorted(r["instance_id"] for r in rows)
    if len(ids) != len(set(ids)):
        print("معرفات مكررة — رفض الكتابة", file=sys.stderr)
        return 1

    doc = {
        "source": f"{DATASET} (test split, HF datasets-server)",
        "fetched": FETCH_DATE,
        "repo_filter": REPO_FILTER,
        "gold_patch_excluded": "deliberately — the measure is zyko not the oracle",
        "instances": sorted(rows, key=lambda r: r["instance_id"]),
    }
    out = Path(args.out)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"كُتب {out} — {len(rows)} حالة (منها أي معرفات جديدة)", file=sys.stderr)
    old = json.loads(Path("benchmarks/data/swe_bench_lite_requests.json").read_text())["instances"]
    old_ids = {i["instance_id"] for i in old}
    new_ids = [i for i in ids if i not in old_ids]
    print(f"الحالات القديمة: {len(old_ids)} — الجديدة المضافة: {len(new_ids)}", file=sys.stderr)
    for i in ids:
        print(f"  {i}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
