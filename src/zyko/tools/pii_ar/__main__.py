"""واجهة سطر الأوامر — يعمل مباشرة على Termux.

Usage:
  python -m zyko_pii_ar scan "نص فيه 0512345678"
  python -m zyko_pii_ar redact "نص" --mode placeholder
  python -m zyko_pii_ar scan --file input.txt --format json
"""

from __future__ import annotations

import argparse
import json
import sys

from .engine import TYPE_LABELS, PIIScanner, redact

VALID_TYPES = list(TYPE_LABELS)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m zyko.tools.pii_ar",
        description="كشف وحجب البيانات الشخصية العربية — حتمي 100%",
    )
    p.add_argument("command", choices=["scan", "redact"], help="العملية المطلوبة")
    p.add_argument("text", nargs="?", default=None, help="النص المدخل")
    p.add_argument("--file", "-f", default=None, help="اقرأ النص من ملف")
    p.add_argument(
        "--mode",
        choices=["mask", "placeholder", "hash"],
        default="mask",
        help="نمط الحجب (لأمر redact)",
    )
    p.add_argument(
        "--types", nargs="*", default=None, choices=VALID_TYPES, help="قصر الكشف على أنواع محددة"
    )
    p.add_argument("--format", choices=["text", "json"], default="text", help="صيغة الإخراج")
    p.add_argument(
        "--arabic-digits", action="store_true", help="أظهر الأرقام في الخلاصة بالأرقام العربية"
    )
    p.add_argument(
        "--min-confidence", type=float, default=0.5, help="الحد الأدنى للثقة (افتراضي 0.5)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"خطأ في قراءة الملف: {exc}", file=sys.stderr)
            return 2
    elif args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    scanner = PIIScanner(min_confidence=args.min_confidence)
    try:
        if args.command == "scan":
            findings = scanner.scan(text, types=args.types)
        else:
            cleaned, findings = redact(text, mode=args.mode, types=args.types, scanner=scanner)
    except Exception as exc:  # pragma: no cover
        print(f"خطأ غير متوقع: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        payload = {
            "tool": "zyko_pii_ar",
            "command": args.command,
            "count": len(findings),
            "findings": [f.to_dict() for f in findings],
        }
        if args.command == "redact":
            payload["redacted"] = cleaned
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if args.command == "redact":
            print(cleaned)
            print("-" * 30)
        if not findings:
            print("لا توجد بيانات شخصية مكتشفة.")
        for f in findings:
            label = TYPE_LABELS[f.type]
            validity = "✓" if f.valid else "؟"
            print(f"[{label}] {f.value}  ({f.start}→{f.end}, ثقة={f.confidence:.2f} {validity})")
        print(f"المجموع: {len(findings)}")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
