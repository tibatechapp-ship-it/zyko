"""CLI الحاكم الشكلي — أكواد خروج صادقة: 0 قبول / 1 رفض / 2 تعذّر التحقق.

    python -m zyko.tools.formal مسار_الملف.py
    python -m zyko.tools.formal --stdin < proposal.py
"""

from __future__ import annotations

import argparse
import sys

from .engine import VerdictKind, check_source, evidence_lines, summarize

EXIT_ACCEPT = 0
EXIT_REJECT = 1
EXIT_UNKNOWN = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zyko.tools.formal",
        description="الحاكم الشكلي: تحكيم العقود المعلنة سكونياً (بلا تنفيذ للمقترح)",
    )
    parser.add_argument("path", nargs="?", default=None, help="مسار ملف بايثون")
    parser.add_argument("--stdin", action="store_true", help="اقرأ المقترح من المدخل القياسي")
    parser.add_argument("--json", action="store_true", help="أخرج ملخصاً قابلاً للتوقيع بصيغة JSON")
    args = parser.parse_args(argv)

    if args.stdin:
        source = sys.stdin.read()
    elif args.path:
        try:
            with open(args.path, "r", encoding="utf-8") as fh:
                source = fh.read()
        except OSError as exc:
            print(f"❌ لا يمكن قراءة الملف: {exc}", file=sys.stderr)
            return EXIT_UNKNOWN
    else:
        parser.error("حدّد مساراً أو استخدم --stdin")
        return EXIT_UNKNOWN  # pragma: no cover — error() يخرج بنفسه

    report = check_source(source)
    if args.json:
        import json

        print(json.dumps(summarize(report), ensure_ascii=False))
    else:
        tag = {
            VerdictKind.ACCEPT: "قبول",
            VerdictKind.REJECT: "رفض",
            VerdictKind.UNKNOWN: "تعذّر التحقق",
        }[report.verdict]
        print(f"[الحاكم الشكلي] {tag}: دوال بعقود = {report.functions_with_contracts}, "
              f"توجيهات = {report.directives_checked}")
        for line in evidence_lines(report):
            print(f"  - {line}")
    if report.verdict is VerdictKind.ACCEPT:
        return EXIT_ACCEPT
    if report.verdict is VerdictKind.REJECT:
        return EXIT_REJECT
    return EXIT_UNKNOWN


if __name__ == "__main__":
    sys.exit(main())
