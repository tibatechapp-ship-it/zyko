"""واجهة سطر أوامر المحرك على المجلدات القائمة — تشغيل مباشر: python -m zyko.workspace.

الأوامر:
  run     مراجعة ← إصلاح لمجلد بايثون قائم (لا كتابة افتراضيًا)
  gate    بوابة المرحلة 5 كاملة (ست بوابات كمية على مراسٍ عربية)
  promise جدول ضمانات المحرك على المجلدات القائمة

أكواد الخروج (اصطلاح المراحل):
  0 الحكم «مقبول» أو البوابة ناجحة   1 ملاحظات متبقية/بوابة فاشلة
  2 خطأ استخدام أو فشل مهيكل

الحذر مع قرص المستخدم: الافتراضي تجربة جافة لا تكتب شيئًا؛ --out يكتب
نسخة إلى مجلد جديد فارغ؛ --in-place يعدّل المجلد الأصلي نفسه ويتطلب
--yes صراحةً كي لا يُمسّ مشروع بلا إذن.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zyko.workspace.engine import MAX_ROUNDS, WRITE_COPY, WRITE_INPLACE, WRITE_NONE, WorkspaceEngine
from zyko.workspace.gate import run_phase5_gate
from zyko.workspace.report import (
    workspace_promise_text,
    workspace_result_to_json,
    workspace_result_to_text,
    workspace_summary_line,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zyko.workspace",
        description=(
            "المحرك على أرض الواقع: مراجعة ← إصلاح حتمي لمجلد بايثون قائم"
            " — بلا نموذج وبلا شبكة، ولا كتابة إلا بإذن صريح"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="مراجعة ← إصلاح لمجلد قائم (تجربة جافة افتراضيًا)")
    p_run.add_argument("--src", required=True, help="مجلد المشروع القائم")
    p_run.add_argument(
        "--out",
        default=None,
        help="اكتب نسخة مُصلَحة إلى هذا المجلد (يجب أن يكون جديدًا وفارغًا)",
    )
    p_run.add_argument(
        "--in-place",
        action="store_true",
        help="عدّل الملفات المُصلَحة في المجلد الأصلي نفسه (يتطلب --yes)",
    )
    p_run.add_argument(
        "--yes",
        action="store_true",
        help="تأكيد صريح مطلوب مع --in-place — كي لا يُمسّ مشروعك بلا إذن",
    )
    p_run.add_argument(
        "--rounds",
        type=int,
        default=1,
        help=f"جولات مراجعة←إصلاح (0 مراجعة فقط، السقف {MAX_ROUNDS})",
    )
    p_run.add_argument(
        "--fail-under",
        type=int,
        default=90,
        help="حد الخروج 0: أدنى درجة بعد الإصلاح ≥ هذا الحد (افتراضي 90)",
    )
    p_run.add_argument("--format", choices=("text", "json", "summary"), default="text")
    p_run.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )

    p_run.add_argument(
        "--html", default=None, help="اكتب لوحة HTML عربية مكتفية ذاتيًا إلى هذا الملف"
    )

    p_gate = sub.add_parser("gate", help="بوابة قبول المرحلة 5 (ست بوابات)")
    p_gate.add_argument("--max-seconds", type=float, default=5.0)

    sub.add_parser("promise", help="جدول ضمانات المحرك على المجلدات القائمة")
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    # ---- تحقق استخدام على مستوى CLI (رسائل عربية، خروج 2)
    if args.in_place and args.out:
        print(
            "خطأ: اختر إما --out (نسخة جديدة) أو --in-place (تعديل موضعي) — لا كليهما معًا",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.in_place and not args.yes:
        print(
            "خطأ: التعديل الموضعي --in-place يتطلب --yes صراحةً — كي لا يُمسّ مشروعك بلا إذن",
            file=sys.stderr,
        )
        return EXIT_USAGE
    out = Path(args.out) if args.out else None
    if out is not None and out.exists() and any(out.iterdir()):
        print(
            f"خطأ: مجلد الإخراج «{out}» غير فارغ — اختر مجلدًا جديدًا حتى لا يُكتب فوق عمل قائم",
            file=sys.stderr,
        )
        return EXIT_USAGE

    write = WRITE_INPLACE if args.in_place else (WRITE_COPY if out is not None else WRITE_NONE)
    engine = WorkspaceEngine()
    result = engine.run(
        args.src,
        rounds=args.rounds,
        write=write,
        out_dir=out,
        confirm_inplace=args.yes,
    )
    if args.format == "json":
        print(workspace_result_to_json(result, include_timing=args.include_timing))
    elif args.format == "summary":
        print(workspace_summary_line(result))
    else:
        print(workspace_result_to_text(result))
    if getattr(args, "html", None):
        # لوحة HTML بجانب المخرجات النصية — الطباعة على stderr كي يبقى stdout حتميًا.
        from zyko.factory.report_html import workspace_result_html, write_html_panel

        write_html_panel(args.html, workspace_result_html(result))
        print(f"كُتبت لوحة HTML: {args.html}", file=sys.stderr)
    if not result.ok:
        return EXIT_USAGE
    if result.min_score_after is not None and result.min_score_after < args.fail_under:
        print(
            f"أدنى درجة بعد الإصلاح ({result.min_score_after}) دون الحد المطلوب"
            f" ({args.fail_under}) — تبقى {result.open_total + result.manual_total}"
            " ملاحظة يُعالجها الإنسان",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_gate(args: argparse.Namespace) -> int:
    gate_result = run_phase5_gate(max_seconds=args.max_seconds)
    print(gate_result.table_ar())
    return EXIT_OK if gate_result.ok else EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "gate":
        return cmd_gate(args)
    print(workspace_promise_text())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
