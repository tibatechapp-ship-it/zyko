"""واجهة سطر أوامر حلقة التغذية الراجعة — تشغيل مباشر: python -m zyko.pipeline.

الأوامر:
  run     الأمر الواحد: وصف عربي ⇒ مشروع مولود مُراجَع مُصلَح على القرص
  gate    بوابة المرحلة 4 كاملة (ست بوابات كمية على مراسٍ عربية)
  stages  جدول مراحل الحلقة وضمانات كل مرحلة

أكواد الخروج (اصطلاح المراحل الثلاث):
  0 الحكم «مقبول» أو البوابة ناجحة   1 ملاحظات متبقية/بوابة فاشلة
  2 خطأ استخدام أو فشل مهيكل
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zyko.pipeline.engine import MAX_ROUNDS, PipelineEngine
from zyko.pipeline.gate import run_phase4_gate
from zyko.pipeline.report import (
    pipeline_result_to_json,
    pipeline_result_to_text,
    pipeline_summary_line,
    stages_table_text,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m zyko.pipeline",
        description=(
            "حلقة التغذية الراجعة الحتمية: توليد ← مراجعة ← إصلاح في أمر واحد — بلا نموذج وبلا شبكة"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="وصف عربي ⇒ مشروع مولود مُراجَع مُصلَح (أمر واحد)")
    p_run.add_argument("--description", required=True, help="وصف عربي للمشروع المطلوب")
    p_run.add_argument("--out", required=True, help="مجلد الإخراج (يجب أن يكون جديدًا وفارغًا)")
    p_run.add_argument(
        "--rounds",
        type=int,
        default=1,
        help=f"جولات مراجعة←إصلاح بعد التوليد (0 مراجعة فقط، السقف {MAX_ROUNDS})",
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="لا تكتب شيئًا على القرص — الحلقة كاملة في الذاكرة",
    )
    p_run.add_argument("--git", action="store_true", help="git init والتزام أول (قبل الإصلاحات)")
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

    p_gate = sub.add_parser("gate", help="بوابة قبول المرحلة 4 (ست بوابات)")
    p_gate.add_argument("--max-seconds", type=float, default=5.0)

    sub.add_parser("stages", help="جدول مراحل الحلقة وضمانات كل مرحلة")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if not args.dry_run and out.exists() and any(out.iterdir()):
        print(
            f"خطأ: المجلد «{out}» غير فارغ — اختر مجلدًا جديدًا حتى لا يُكتب فوق عمل قائم",
            file=sys.stderr,
        )
        return EXIT_USAGE
    engine = PipelineEngine()
    result = engine.run(
        args.description,
        out,
        git_init=args.git,
        rounds=args.rounds,
        write=not args.dry_run,
    )
    if args.format == "json":
        print(pipeline_result_to_json(result, include_timing=args.include_timing))
    elif args.format == "summary":
        print(pipeline_summary_line(result))
    else:
        print(pipeline_result_to_text(result))
    if not result.ok:
        return EXIT_USAGE
    if result.min_score_after < args.fail_under:
        print(
            f"أدنى درجة بعد الإصلاح ({result.min_score_after}) دون الحد المطلوب"
            f" ({args.fail_under}) — تبقى {result.open_total + result.manual_total}"
            " ملاحظة يُعالجها الإنسان",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    return EXIT_OK


def _cmd_gate(args: argparse.Namespace) -> int:
    gate_result = run_phase4_gate(max_seconds=args.max_seconds)
    print(gate_result.table_ar())
    return EXIT_OK if gate_result.ok else EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "gate":
        return _cmd_gate(args)
    print(stages_table_text())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
