#!/usr/bin/env python3
"""مولّد manifest عينات المرحلة 3 — التوقعات مكتوبة يدويًا والمولّد يتحقق منها.

يعمل المولّد المُصلِح فعليًا على كل عينة، ويطابق السلوك مع التوقعات
المكتوبة أدناه (التي صيغت من التصميم لا من الملاحظة)، فإن خالفه السلوك
خرج برمز 2 وعربيًا — فلا يُكتب manifest يثبت شيئًا خاطئًا.

الاستخدام: python scripts/gen_phase3_manifest.py  (من جذر المستودع)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from zyko.fixer.engine import FixerEngine  # noqa: E402
from zyko.fixer.fixes import AUTO_FIXABLE, MANUAL_RULES  # noqa: E402

# التوقعات المكتوبة يدويًا من التصميم (لا من مخرجات المحرك):
EXPECTATIONS: dict[str, dict[str, list[str]]] = {
    "bad_errors.py": {
        "expect_fixed": ["R-ERR-001", "R-ERR-003", "R-ERR-004", "R-ERR-006"],
        "allow_open": ["R-ERR-005"],  # أمر صدفة نصي: إزالة shell تكسر المعنى
        "expect_manual": [
            "R-ERR-002",
            "R-ERR-005",
            "R-ERR-007",
            "R-ERR-008",
            "R-ERR-009",
            "R-ERR-010",
        ],
    },
    "bad_security.py": {
        "expect_fixed": ["R-SEC-103", "R-SEC-106", "R-SEC-107"],
        "allow_open": [],
        "expect_manual": ["R-SEC-101", "R-SEC-102", "R-SEC-104", "R-SEC-105", "R-SEC-108"],
    },
    "bad_quality.py": {
        "expect_fixed": ["R-QLT-204", "R-QLT-206", "R-QLT-207", "R-QLT-209"],
        "allow_open": [],
        "expect_manual": ["R-QLT-201", "R-QLT-202", "R-QLT-203", "R-QLT-205", "R-QLT-208"],
    },
    "fix_edges.py": {
        "expect_fixed": [
            "R-ERR-001",
            "R-ERR-003",
            "R-ERR-005",
            "R-ERR-006",
            "R-SEC-103",
            "R-SEC-106",
            "R-SEC-107",
            "R-QLT-204",
            "R-QLT-206",
            "R-QLT-207",
            "R-QLT-209",
        ],
        "allow_open": ["R-ERR-004"],  # فتح غير مباشر عبر تابع: لا مسار آمن
        "expect_manual": ["R-ERR-002", "R-QLT-205"],
    },
}
CLEAN = ["clean_good.py"]


def main() -> int:
    fixer = FixerEngine()
    problems: list[str] = []
    fixed_anywhere: set[str] = set()
    manual_anywhere: set[str] = set()
    for name, exp in EXPECTATIONS.items():
        result = fixer.fix_file(ROOT / "samples" / "fix" / name)
        if result.parse_error is not None:
            problems.append(f"{name}: {result.parse_error}")
            continue
        statuses: dict[str, set[str]] = {}
        for o in result.outcomes:
            statuses.setdefault(o.rule_id, set()).add(o.status)
        for rid in exp["expect_fixed"]:
            st = statuses.get(rid, set())
            if st != {"fixed"}:
                problems.append(f"{name}: {rid} توقعه «fixed» والواقع {sorted(st) or 'بلا ملاحظة'}")
            else:
                fixed_anywhere.add(rid)
        for rid in exp["expect_manual"]:
            st = statuses.get(rid, set())
            if rid in AUTO_FIXABLE:
                if "open" not in st:
                    problems.append(
                        f"{name}: {rid} آلية وكان يجب أن تبقى مفتوحة؛ الواقع {sorted(st)}"
                    )
            elif "manual" not in st:
                problems.append(f"{name}: {rid} كان يجب أن تظهر يدوية؛ الواقع {sorted(st)}")
            manual_anywhere.add(rid)
        allowed = set(exp["allow_open"]) | set(exp["expect_manual"])
        for rid, st in statuses.items():
            if rid in AUTO_FIXABLE and "open" in st and rid not in allowed:
                problems.append(f"{name}: {rid} مفتوحة بلا تصريح في التوقعات")
    dead_fix = sorted(set(AUTO_FIXABLE) - fixed_anywhere)
    silent_manual = sorted(set(MANUAL_RULES) - manual_anywhere)
    if dead_fix:
        problems.append("مسارات آلية لا تُصلَح في أي عينة: " + "، ".join(dead_fix))
    if silent_manual:
        problems.append("قواعد يدوية لا تظهر في أي عينة: " + "، ".join(silent_manual))
    # العينة النظيفة يجب ألا تمس
    clean = fixer.fix_file(ROOT / "samples" / "fix" / CLEAN[0])
    if clean.changed or clean.outcomes:
        problems.append(f"{CLEAN[0]}: العينة النظيفة تغيرت — إنذار كاذب في الإصلاح")
    if problems:
        print("فشل توليد manifest — السلوك خالف التوقعات:", file=sys.stderr)
        for p in problems:
            print(" -", p, file=sys.stderr)
        return 2
    manifest = {
        "defective": [{"file": name, **exp} for name, exp in EXPECTATIONS.items()],
        "clean": CLEAN,
    }
    out = ROOT / "samples" / "fix" / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"تم: {out} — {len(EXPECTATIONS)} ملفات معيبة، كل التوقعات مطابقة للسلوك")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
