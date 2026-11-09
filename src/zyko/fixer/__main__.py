"""واجهة سطر أوامر المُصلِح — تشغيل مباشر: python -m zyko.fixer.

الأوامر:
  fix    إصلاح ملف أو مجلد (تجريبي افتراضيًا؛ --write للكتابة، --diff للفرق)
  check  هل تبقى ملاحظات قابلة للإصلاح الآلي؟ (صديق CI: خروج 1 يعني نعم)
  gate   بوابة المرحلة 3 كاملة (ست بوابات كمية على عينات المرساة)
  rules  جدول مسارات الإصلاح (آلي/يدوي)

أكواد الخروج (اصطلاح المرحلتين السابقتين):
  0 سليم/بوابة ناجحة   1 ملاحظات أو بوابة فاشلة   2 خطأ استخدام أو مسار
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zyko.fixer.engine import FixerEngine
from zyko.fixer.gate import run_phase3_gate
from zyko.fixer.report import (
    fix_result_to_json,
    fix_result_to_text,
    fix_results_to_json,
    fix_results_to_text,
    fix_rules_table_text,
    fix_summary_line,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zyko.fixer",
        description="مُصلِح الشيفرة الحتمي عربيًا — 12 مسارًا آمنًا فوق 38 قاعدة، بلا نموذج وبلا شبكة",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fix = sub.add_parser("fix", help="إصلاح ملف أو مجلد (تجريبي افتراضيًا)")
    p_fix.add_argument("--path", required=True, help="ملف أو مجلد للإصلاح")
    p_fix.add_argument(
        "--write", action="store_true", help="اكتب النواتج على القرص (المتحقق منها فقط)"
    )
    p_fix.add_argument("--diff", action="store_true", help="أضف فرقًا موحدًا بعد التقرير")
    p_fix.add_argument("--format", choices=("json", "text", "summary"), default="text")
    p_fix.add_argument(
        "--rules",
        default=None,
        help="قيّد القواعد الآلية بفاصلة (مثال: R-SEC-103,R-SEC-106)",
    )
    p_fix.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )

    p_fix.add_argument(
        "--html", default=None, help="اكتب لوحة HTML عربية مكتفية ذاتيًا إلى هذا الملف"
    )

    p_check = sub.add_parser("check", help="خروج 1 إن بقيت ملاحظات قابلة للإصلاح الآلي")
    p_check.add_argument("--path", required=True, help="ملف أو مجلد للفحص")

    p_gate = sub.add_parser("gate", help="بوابة قبول المرحلة 3 (ست بوابات)")
    p_gate.add_argument("--samples", default=None, help="مجلد العينات (افتراضي samples/fix)")
    p_gate.add_argument("--max-seconds", type=float, default=5.0)

    sub.add_parser("rules", help="جدول مسارات الإصلاح")
    return parser


def _parse_rules(spec: str | None) -> tuple[str, ...] | None:
    if not spec:
        return None
    return tuple(x.strip() for x in spec.split(",") if x.strip())


def _unified_diff(before: str, after: str, path: str) -> str:
    import difflib

    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{path} (قبل)",
            tofile=f"{path} (بعد)",
            lineterm="",
        )
    )


def cmd_fix(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"خطأ: المسار غير موجود: {target}", file=sys.stderr)
        return EXIT_USAGE
    rules = _parse_rules(args.rules)
    engine = FixerEngine(rules=rules)
    if target.is_file():
        results = [engine.fix_file(target)]
    else:
        results = engine.fix_path(target)
    if not results:
        print("لا ملفات بايثون في هذا المسار", file=sys.stderr)
        return EXIT_USAGE
    if args.format == "json":
        print(
            fix_result_to_json(results[0], include_timing=args.include_timing)
            if len(results) == 1
            else fix_results_to_json(results, include_timing=args.include_timing)
        )
    elif args.format == "summary":
        print(fix_summary_line(results))
    else:
        print(fix_result_to_text(results[0]) if len(results) == 1 else fix_results_to_text(results))
    if getattr(args, "html", None):
        # لوحة HTML بجانب المخرجات النصية — الطباعة على stderr كي يبقى stdout حتميًا.
        from zyko.factory.report_html import fixer_results_html, write_html_panel

        write_html_panel(args.html, fixer_results_html(results))
        print(f"كُتبت لوحة HTML: {args.html}", file=sys.stderr)
    if args.diff:
        for r in results:
            if r.changed:
                print()
                print(
                    _unified_diff(
                        Path(r.path).read_text(encoding="utf-8") if Path(r.path).is_file() else "",
                        r.fixed_source,
                        r.path,
                    )
                )
    if args.write:
        written = 0
        for r in results:
            if r.changed and r.parse_error is None and Path(r.path).is_file():
                Path(r.path).write_text(r.fixed_source, encoding="utf-8")
                written += 1
        print(f"كُتب {written} ملفًا على القرص (النواتج المتحقق منها فقط)", file=sys.stderr)
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"خطأ: المسار غير موجود: {target}", file=sys.stderr)
        return EXIT_USAGE
    engine = FixerEngine()
    results = [engine.fix_file(target)] if target.is_file() else engine.fix_path(target)
    if not results:
        print("لا ملفات بايثون في هذا المسار", file=sys.stderr)
        return EXIT_USAGE
    remaining = sum(r.fixable_remaining for r in results)
    if remaining:
        print(
            f"تبقى {remaining} ملاحظة قابلة للإصلاح الآلي — شغّل: python -m zyko.fixer fix --path {target} --write",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    print("لا ملاحظات قابلة للإصلاح الآلي — النص حسب أحدث إصلاح", file=sys.stderr)
    return EXIT_OK


def cmd_gate(args: argparse.Namespace) -> int:
    gate_result = run_phase3_gate(args.samples, max_seconds=args.max_seconds)
    print(gate_result.table_ar())
    return EXIT_OK if gate_result.ok else EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "fix":
        return cmd_fix(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "gate":
        return cmd_gate(args)
    print(fix_rules_table_text())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
