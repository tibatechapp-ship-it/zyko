"""واجهة سطر الأوامر — يعمل مباشرة على Termux.

Usage:
  python -m zyko_rtl check --path src/ --format json
  python -m zyko_rtl check --path style.css
  python -m zyko_rtl check --text ".x{text-align:left}" --lang css
  python -m zyko_rtl rules

أكواد الخروج: 0 نظيف · 1 ملاحظات عند العتبة · 2 خطأ تشغيلي
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import (
    RULE_CATALOG,
    SEVERITIES,
    SEVERITY_AR,
    SEVERITY_RANK,
    RTLChecker,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m zyko.tools.rtl",
        description="كاشف مشاكل الاتجاه RTL — حتمي 100% بلا نماذج",
    )
    p.add_argument("command", choices=["check", "rules"], help="العملية المطلوبة")
    p.add_argument("--path", "-p", default=None, help="ملف أو مجلد لفحصه (يتكرر فرعيًا)")
    p.add_argument("--text", "-t", default=None, help="نص خام لفحصه مباشرة (يتطلب --lang)")
    p.add_argument(
        "--lang",
        choices=["css", "html", "python", "text"],
        default=None,
        help="لسان النص الخام (افتراضي: text)",
    )
    p.add_argument("--format", choices=["text", "json"], default="text", help="صيغة الإخراج")
    p.add_argument(
        "--min-severity", choices=SEVERITIES, default="info", help="أدنى خطورة تُعرض (افتراضي: info)"
    )
    p.add_argument(
        "--fail-on",
        choices=SEVERITIES,
        default="warning",
        help="الخطورة التي تجعل كود الخروج 1 (افتراضي: warning)",
    )
    return p


def _print_text(findings, files_scanned: int) -> None:
    if not findings:
        print(f"لا ملاحظات — فُحص {files_scanned} ملفًا. الاتجاه سليم ✓")
        return
    for f in findings:
        print(f"[{SEVERITY_AR[f.severity]}] {f.rule}  {f.file}:{f.line}:{f.col}")
        print(f"   {f.message}")
        print(f"   ↳ الحل: {f.suggestion}")
        if f.excerpt:
            print(f"   | {f.excerpt}")
        print()
    by_sev = {s: 0 for s in SEVERITIES}
    for f in findings:
        by_sev[f.severity] += 1
    print(
        f"المجموع: {len(findings)} ملاحظة"
        f" (خطأ {by_sev['error']}، تحذير {by_sev['warning']}،"
        f" معلومة {by_sev['info']}) على {files_scanned} ملفًا"
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "rules":
        print(f"{'القاعدة':<14}{'الخطورة':<10}الوصف")
        print("-" * 70)
        for rule_id, (sev, desc) in RULE_CATALOG.items():
            print(f"{rule_id:<14}{SEVERITY_AR[sev]:<10}{desc}")
        return 0

    checker = RTLChecker(min_severity=args.min_severity)

    if args.text is not None:
        lang = args.lang or "text"
        findings = checker.check_source(args.text, lang, "<inline>")
        files_scanned = 1
    elif args.path is not None:
        try:
            findings, files_scanned = checker.check_path(args.path)
        except (ValueError, FileNotFoundError, OSError, PermissionError) as exc:
            print(f"خطأ: {exc}", file=sys.stderr)
            return 2
    else:
        print("خطأ: حدد --path لملف/مجلد أو --text لنص خام.", file=sys.stderr)
        return 2

    if args.format == "json":
        by_sev = {s: 0 for s in SEVERITIES}
        for f in findings:
            by_sev[f.severity] += 1
        print(
            json.dumps(
                {
                    "tool": "zyko_rtl",
                    "version": __version__,
                    "files_scanned": files_scanned,
                    "count": len(findings),
                    "by_severity": by_sev,
                    "findings": [f.to_dict() for f in findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_text(findings, files_scanned)

    threshold = SEVERITY_RANK[args.fail_on]
    if any(SEVERITY_RANK[f.severity] >= threshold for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
