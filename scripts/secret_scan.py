#!/usr/bin/env python3
"""secret_scan CLI — بوابة الأسرار لدورة النشر (الحزمة 0.5 في publish-release-cycle.sh).

الاستدعاءان المعلنان كما يستدعيهما دورة النشر:
  * ``--diff A..B``  : أسطر المضافة في مدى git تُفحص بأنماط الأسرار
  * ``--tree DIR``   : شجرة كاملة تحت السقوف المعلنة

السياسات (كلها معلنة لا ضمنية):
  * النمط الواحد من ``zyko.utils.secret_scan`` — لا جدول موازٍ أبداً
  * الإعفاء بالعلامة الصريحة ``zyko:secret-ok`` في السطر (فحص
    ``scan_text`` يحترمها) — للاختبارات والتوثيق، تُبحث بـ grep
  * الإثبات بالبصمة sha16 لا بطباعة القيمة — الدليل يتحقق ولا يسرَّب
  * الأسطر المضافة فقط في وضع diff (حذف السر ليس جريمة — عقد
    ``zyko.benchmarks.patch_audit`` نفسه)
  * الخروج: 1 عند إصابة حرجة وحدها (medium تُسجَّل لا تمنع)،
    2 خطأ استخدام
  * التسلسل حتمي بالبايت — نفس الفحص ⇒ نفس المخرجات
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# تمهيد الجذر: بوابة دورة النشر تعمل من أي بايثون حتى لو لم تُثبَّت الحزمة
_REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from zyko.utils.secret_scan import scan_text, scan_to_json, scan_tree  # noqa: E402

SCHEMA = "zyko.secret_scan_cli/1"


def _toplevel() -> str:
    """جذر المستودع من cwd — وضع diff يعمل على مستودع لا على جزء منه."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("FATAL: وضع --diff يتطلب مستودع git (rev-parse فشل)")
    return proc.stdout.strip()


def _diff_payload(repo: str, rng: str) -> dict:
    """فحص أسطر المضافة في مدى git — من مستخرج الفرق الموحد نفسه."""
    proc = subprocess.run(
        ["git", "-C", repo, "diff", rng],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"FATAL: فشل git diff للمدى {rng}: {proc.stderr.strip()}")
    from zyko.benchmarks.patch_audit import added_lines  # مستورَد كسول — طبقة benchmarks

    added = added_lines(proc.stdout)
    hits: list[dict] = []
    for fpath, lineno, text in added:
        for hit in scan_text(text):
            d = hit.to_dict()
            d["file"] = fpath
            d["line_in_file"] = lineno
            hits.append(d)
    return {
        "schema": SCHEMA,
        "mode": "diff",
        "range": rng,
        "added_count": len(added),
        "hit_count": len(hits),
        "hits": hits,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="بوابة الأسرار الحتمية — شجرة أو مدى فرق")
    ap.add_argument("--tree", dest="tree", help="فحص شجرة كاملة تحت السقوف المعلنة")
    ap.add_argument("--diff", dest="diff", help="فحص أسطر المضافة في مدى git مثل origin/main..HEAD")
    ap.add_argument("--repo", default="", help="جذر المستودع لوضع diff — افتراضاً rev-parse من cwd")
    args = ap.parse_args()
    if bool(args.tree) == bool(args.diff):
        print("FATAL: اختر وضعاً واحداً: --tree أو --diff", file=sys.stderr)
        return 2
    if args.tree:
        payload = scan_tree(args.tree)
        payload["schema"] = SCHEMA
        payload["mode"] = "tree"
        payload["root"] = str(Path(args.tree).resolve())
    else:
        repo = args.repo or _toplevel()
        payload = _diff_payload(repo, args.diff)
    print(scan_to_json(payload))
    critical = any(h["severity"] == "critical" for h in payload["hits"])
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
