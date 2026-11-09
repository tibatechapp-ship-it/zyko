"""واجهة سطر أوامر حارس الجودة — تشغيل مباشر: python -m zyko.baseline.

الأوامر:
  update  سجّل الوضع الحالي كخط أساس (يكتب ملفًا واحدًا فقط)
  check   قارن الوضع الحالي بخط الأساس (قراءة فقط دائمًا)
  show    اعرض خط الأساس المخزّن وسجل التشغيلات (قراءة فقط)
  gate    بوابة المرحلة 6 كاملة (ست بوابات كمية على مراسٍ عربية)
  promise جدول ضمانات حارس الجودة

أكواد الخروج (اصطلاح المراحل):
  0 لا تراجع/بوابة ناجحة   1 تراجع مكتشف أو لا خط أساس   2 خطأ استخدام أو فشل مهيكل

الأمان على قرصك: ``check`` و``show`` لا يكتبان شيئًا إطلاقًا؛
``update`` يكتب ملفًا واحدًا فقط (``.zyko/baseline.json``) ولا يلمس
أي ملف مشروع؛ تقرير HTML يُكتب فقط عند طلب ``--html`` صراحةً.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zyko.baseline.engine import (
    SCHEMA,
    BaselineEngine,
    BaselineUpdateResult,
    default_baseline_path,
)
from zyko.baseline.gate import run_phase6_gate
from zyko.baseline.report import (
    baseline_check_summary_line,
    baseline_check_to_html,
    baseline_check_to_json,
    baseline_check_to_text,
    baseline_promise_text,
    baseline_update_summary_line,
    baseline_update_to_json,
    baseline_update_to_text,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zyko.baseline",
        description=(
            "حارس الجودة عبر الزمن: خط أساس حتمي وكشف تراجع لمجلد بايثون قائم"
            " — check يقرأ فقط، وupdate يكتب خط الأساس وحده"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--src", required=True, help="مجلد المشروع القائم")
        p.add_argument(
            "--baseline",
            default=None,
            help="ملف خط الأساس (الافتراضي: <src>/.zyko/baseline.json)",
        )
        p.add_argument("--format", choices=("text", "json", "summary"), default="text")
        p.add_argument(
            "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
        )

    p_update = sub.add_parser("update", help="سجّل الوضع الحالي كخط أساس")
    _common(p_update)

    p_check = sub.add_parser("check", help="قارن الوضع الحالي بخط الأساس (قراءة فقط)")
    _common(p_check)
    p_check.add_argument(
        "--html",
        default=None,
        help="اكتب تقرير HTML عربي حتمي إلى هذا المسار (اختياري)",
    )

    p_show = sub.add_parser("show", help="اعرض خط الأساس المخزّن وسجل التشغيلات")
    _common(p_show)

    p_gate = sub.add_parser("gate", help="بوابة قبول المرحلة 6 (ست بوابات)")
    p_gate.add_argument("--max-seconds", type=float, default=5.0)

    sub.add_parser("promise", help="جدول ضمانات حارس الجودة")
    return parser


def _print_update(result: BaselineUpdateResult, fmt: str, timing: bool) -> None:
    if fmt == "json":
        print(baseline_update_to_json(result, include_timing=timing))
    elif fmt == "summary":
        print(baseline_update_summary_line(result))
    else:
        print(baseline_update_to_text(result))


def _cmd_update(args: argparse.Namespace) -> int:
    result = BaselineEngine().update(args.src, baseline_path=args.baseline)
    _print_update(result, args.format, args.include_timing)
    return EXIT_OK if result.ok else EXIT_USAGE


def _cmd_check(args: argparse.Namespace) -> int:
    result = BaselineEngine().check(args.src, baseline_path=args.baseline)
    if args.format == "json":
        print(baseline_check_to_json(result, include_timing=args.include_timing))
    elif args.format == "summary":
        print(baseline_check_summary_line(result))
    else:
        print(baseline_check_to_text(result))
    if not result.ok:
        return EXIT_USAGE
    if args.html:
        html_path = Path(args.html)
        if html_path.is_dir():
            print(f"خطأ: مسار تقرير HTML مجلد لا ملف: {html_path}", file=sys.stderr)
            return EXIT_USAGE
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(baseline_check_to_html(result), encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"خطأ: تعذرت كتابة تقرير HTML: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"تقرير HTML: {html_path}", file=sys.stderr)
    return result.exit_code


def _cmd_show(args: argparse.Namespace) -> int:
    bpath = Path(args.baseline) if args.baseline else default_baseline_path(args.src)
    if not bpath.exists():
        print(
            f"لا خط أساس في: {bpath}\nالإجراء: شغّل «update» أولًا ليُسجَّل الوضع الحالي",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    if bpath.is_dir():
        print(f"خطأ: مسار خط الأساس مجلد لا ملف: {bpath}", file=sys.stderr)
        return EXIT_USAGE
    try:
        stored = json.loads(bpath.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(
            f"خطأ: خط الأساس فاسد ({type(exc).__name__}) — أعِد إنشاءه بأمر update",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not isinstance(stored, dict) or stored.get("schema") != SCHEMA:
        print(
            f"خطأ: خط الأساس بمخطط غير معروف ({stored.get('schema')!r}) — أعِد إنشاءه بأمر update",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.format == "json":
        print(json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_OK
    history = stored.get("history") or []
    files = stored.get("files") or {}
    lines = [
        "حارس الجودة — خط الأساس المخزّن (قراءة فقط)",
        f"الملف: {bpath}",
        f"المخطط: {stored.get('schema')} — تشغيل رقم {stored.get('run_no')}",
        f"الملفات: {stored.get('files_total')} (مراقَب {stored.get('reviewed')},"
        f" تُخُطّي {stored.get('skipped')}) — أدنى درجة {stored.get('min_score')}/100"
        f" — ملاحظات {stored.get('findings_total')}",
    ]
    if history:
        lines.append("سجل التشغيلات (الأحدث في الأسفل):")
        for h in history:
            lines.append(
                f"  تشغيل {h.get('run_no')}: مراقَب {h.get('reviewed')}"
                f" — أدنى درجة {h.get('min_score')}"
                f" — ملاحظات {h.get('findings_total')}"
            )
    if files and args.format != "summary":
        lines.append("-" * 60)
        for path in sorted(files):
            record = files[path]
            lines.append(
                f"  [{path}] درجة {record.get('score')} — ملاحظات {len(record.get('findings') or [])}"
            )
    print("\n".join(lines))
    return EXIT_OK


def _cmd_gate(args: argparse.Namespace) -> int:
    gate_result = run_phase6_gate(max_seconds=args.max_seconds)
    print(gate_result.table_ar())
    return EXIT_OK if gate_result.ok else EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "update":
        return _cmd_update(args)
    if args.command == "check":
        return _cmd_check(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "gate":
        return _cmd_gate(args)
    print(baseline_promise_text())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
