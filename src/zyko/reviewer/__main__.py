"""واجهة سطر أوامر المراجع — تشغيل مباشر: python -m zyko.reviewer.

الأوامر:
  review  مراجعة ملف أو مجلد (--format json|text|summary، --fail-under، --max-critical)
  gate    بوابة المرحلة 2 كاملة (ست بوابات كمية على عينات المرساة)
  rules   جدول القواعد (json|text)

أكواد الخروج (اصطلاح linter المتبع في المرحلة 0):
  0 سليم/بوابة ناجحة   1 ملاحظات أو بوابة فاشلة   2 خطأ استخدام أو مسار
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zyko.reviewer.engine import ReviewEngine, summarize
from zyko.reviewer.gate import run_phase2_gate
from zyko.reviewer.report import (
    result_to_json,
    result_to_text,
    results_to_json,
    results_to_text,
    rules_table_text,
)
from zyko.reviewer.rules import RULES

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zyko.reviewer",
        description="مراجع الشيفرة الحتمي عربيًا — 27 قاعدة AST بلا نموذج وبلا شبكة",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_review = sub.add_parser("review", help="مراجعة ملف أو مجلد")
    p_review.add_argument("--path", required=True, help="ملف أو مجلد للمراجعة")
    p_review.add_argument("--format", choices=("json", "text", "summary"), default="text")
    p_review.add_argument(
        "--fail-under", type=int, default=90, help="الحد الأدنى للنجاح (افتراضي 90)"
    )
    p_review.add_argument(
        "--max-critical", type=int, default=0, help="أقصى عدد ملاحظات حرجة مسموح (افتراضي 0)"
    )
    p_review.add_argument(
        "--include-timing", action="store_true", help="أضف زمن المراجعة (يكسر الحتمية البايتية)"
    )

    p_gate = sub.add_parser("gate", help="بوابة قبول المرحلة 2 (ست بوابات)")
    p_gate.add_argument("--samples", default=None, help="مجلد العينات (افتراضي samples/review)")
    p_gate.add_argument("--min-recall", type=float, default=1.0)
    p_gate.add_argument("--max-seconds", type=float, default=5.0)

    p_rules = sub.add_parser("rules", help="سرد القواعد")
    p_rules.add_argument("--format", choices=("json", "text"), default="text")
    return parser


def _cmd_review(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"خطأ: المسار غير موجود: {target}", file=sys.stderr)
        return EXIT_USAGE
    engine = ReviewEngine()
    if target.is_file():
        results = [engine.review_file(target)]
    else:
        results = engine.review_path(target)
    if not results:
        print("لا ملفات بايثون في هذا المسار", file=sys.stderr)
        return EXIT_USAGE
    if args.format == "json":
        print(
            result_to_json(results[0], include_timing=args.include_timing)
            if len(results) == 1
            else results_to_json(results, include_timing=args.include_timing)
        )
    elif args.format == "summary":
        s = summarize(results)
        counts = s["counts"]
        print(
            f"الملفات: {s['files']} — الملاحظات: {s['total_findings']} — "
            f"حرج {counts['critical']}، عالي {counts['high']}، متوسط {counts['medium']}، "
            f"منخفض {counts['low']}، معلومة {counts['info']} — أقل درجة {s['min_score']}"
        )
    else:
        print(result_to_text(results[0]) if len(results) == 1 else results_to_text(results))
    min_score = min(r.score for r in results)
    critical = sum(r.counts.get("critical", 0) for r in results)
    failed = min_score < args.fail_under or critical > args.max_critical
    return EXIT_FINDINGS if failed else EXIT_OK


def _cmd_gate(args: argparse.Namespace) -> int:
    gate_result = run_phase2_gate(
        args.samples, min_recall=args.min_recall, max_seconds=args.max_seconds
    )
    print(gate_result.table_ar())
    return EXIT_OK if gate_result.ok else EXIT_FINDINGS


def _cmd_rules(args: argparse.Namespace) -> int:
    if args.format == "json":
        import json

        payload = [
            {
                "rule_id": r.rule_id,
                "severity": r.severity,
                "category": r.category,
                "message_ar": r.message_ar,
                "suggestion_ar": r.suggestion_ar,
            }
            for r in RULES
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(rules_table_text(RULES))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "review":
        return _cmd_review(args)
    if args.command == "gate":
        return _cmd_gate(args)
    return _cmd_rules(args)


if __name__ == "__main__":
    raise SystemExit(main())
