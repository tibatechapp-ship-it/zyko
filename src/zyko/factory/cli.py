"""zyko.factory.cli — بوابة المصنع الموحدة: أمر واحد لكل وحدات المحرك.

المصنع كان أربع بوابات منفصلة (``python -m zyko.fixer`` ثم
``.pipeline`` ثم ``.workspace`` ثم ``.baseline``)؛ هذه الوحدة تجمعها
خلف باب واحد::

    zyko factory              # الخريطة (افتراضي بلا أمر فرعي)
    zyko factory map          # الوحدات والعقود وأكواد الخروج
    zyko factory fix          # المرحلة 3 — نفس سلوك python -m zyko.fixer fix
    zyko factory pipeline     # المرحلة 4 — نفس سلوك python -m zyko.pipeline run
    zyko factory workspace    # المرحلة 5 — نفس سلوك python -m zyko.workspace run
    zyko factory baseline     # المرحلة 6 — نفس سلوك python -m zyko.baseline
    zyko factory gates        # بوابات 3+4+5+6 كاملة (24 بوابه) وخلاصة واحدة
    zyko factory dashboard    # لوحة تحكم عربية حتمية (HTML + Markdown) للبوابات

التفويض حرفي: أوامر fix/pipeline/workspace/baseline تستدعي معالجات
الوحدات نفسها (نفس الحجج، نفس أكواد الخروج، نفس الحتمية) — بلا إعادة
تنفيذ ولا انحراف سلوك ممكن. علم ``--html`` متاح في البوابتين معًا.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from zyko.factory.map import factory_map_text

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _add_fix_parser(sub: Any) -> None:
    p = sub.add_parser("fix", help="المرحلة 3 — إصلاح ملف أو مجلد (تجريبي افتراضيًا)")
    p.add_argument("--path", required=True, help="ملف أو مجلد للإصلاح")
    p.add_argument("--write", action="store_true", help="اكتب النواتج على القرص (المتحقق منها فقط)")
    p.add_argument("--diff", action="store_true", help="أضف فرقًا موحدًا بعد التقرير")
    p.add_argument("--format", choices=("json", "text", "summary"), default="text")
    p.add_argument(
        "--rules", default=None, help="قيّد القواعد الآلية بفاصلة (مثال: R-SEC-103,R-SEC-106)"
    )
    p.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )
    p.add_argument("--html", default=None, help="اكتب لوحة HTML عربية إلى هذا الملف")


def _add_pipeline_parser(sub: Any) -> None:
    p = sub.add_parser("pipeline", help="المرحلة 4 — توليد ← مراجعة ← إصلاح في أمر واحد")
    p.add_argument("--description", required=True, help="وصف عربي للمشروع المطلوب")
    p.add_argument("--out", required=True, help="مجلد الإخراج (يجب أن يكون جديدًا وفارغًا)")
    p.add_argument(
        "--rounds", type=int, default=1, help="جولات مراجعة←إصلاح بعد التوليد (0 مراجعة فقط)"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="لا تكتب شيئًا على القرص — الحلقة كاملة في الذاكرة"
    )
    p.add_argument("--git", action="store_true", help="git init والتزام أول (قبل الإصلاحات)")
    p.add_argument(
        "--fail-under", type=int, default=90, help="حد الخروج 0: أدنى درجة بعد الإصلاح ≥ هذا الحد"
    )
    p.add_argument("--format", choices=("text", "json", "summary"), default="text")
    p.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )
    p.add_argument("--html", default=None, help="اكتب لوحة HTML عربية إلى هذا الملف")


def _add_workspace_parser(sub: Any) -> None:
    p = sub.add_parser(
        "workspace", help="المرحلة 5 — مراجعة ← إصلاح لمجلد بايثون قائم (تجربة جافة افتراضيًا)"
    )
    p.add_argument("--src", required=True, help="مجلد المشروع القائم")
    p.add_argument("--out", default=None, help="اكتب نسخة مُصلَحة إلى هذا المجلد (جديد وفارغ)")
    p.add_argument(
        "--in-place",
        action="store_true",
        help="عدّل الملفات المُصلَحة في المجلد الأصلي (يتطلب --yes)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="تأكيد صريح مطلوب مع --in-place — كي لا يُمسّ مشروعك بلا إذن",
    )
    p.add_argument("--rounds", type=int, default=1, help="جولات مراجعة←إصلاح (0 مراجعة فقط)")
    p.add_argument(
        "--fail-under", type=int, default=90, help="حد الخروج 0: أدنى درجة بعد الإصلاح ≥ هذا الحد"
    )
    p.add_argument("--format", choices=("text", "json", "summary"), default="text")
    p.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )
    p.add_argument("--html", default=None, help="اكتب لوحة HTML عربية إلى هذا الملف")


def _add_baseline_parser(sub: Any) -> None:
    p = sub.add_parser("baseline", help="المرحلة 6 — حارس الجودة: خط أساس وكشف تراجع")
    b = p.add_subparsers(dest="baseline_cmd", required=True)

    def _common(pb: Any) -> None:
        pb.add_argument("--src", required=True, help="مجلد المشروع القائم")
        pb.add_argument(
            "--baseline", default=None, help="ملف خط الأساس (الافتراضي: <src>/.zyko/baseline.json)"
        )
        pb.add_argument("--format", choices=("text", "json", "summary"), default="text")
        pb.add_argument(
            "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
        )

    pu = b.add_parser("update", help="سجّل الوضع الحالي كخط أساس (ملف واحد فقط)")
    _common(pu)
    pc = b.add_parser("check", help="قارن الوضع الحالي بخط الأساس (قراءة فقط)")
    _common(pc)
    pc.add_argument("--html", default=None, help="اكتب تقرير HTML عربي حتمي إلى هذا المسار")
    ps = b.add_parser("show", help="اعرض خط الأساس المخزّن وسجل التشغيلات")
    _common(ps)


def _add_gates_parser(sub: Any) -> None:
    p = sub.add_parser("gates", help="بوابات المراحل 3+4+5+6 كاملة (24 بوابه) وخلاصة واحدة")
    p.add_argument("--max-seconds", type=float, default=5.0, help="ميزانية الأداء لكل بوابة")
    p.add_argument("--html", default=None, help="اكتب لوحة التحكم (HTML) إلى هذا الملف")
    p.add_argument("--md", default=None, help="اكتب لوحة التحكم (Markdown) إلى هذا الملف")


def register_to(factory_sub: Any) -> None:
    """ثبّت الأوامر الفرعية للمصنع في حاوية subparsers القائمة."""
    factory_sub.add_parser("map", help="خريطة المصنع: الوحدات والعقود وأكواد الخروج")
    _add_fix_parser(factory_sub)
    _add_pipeline_parser(factory_sub)
    _add_workspace_parser(factory_sub)
    _add_baseline_parser(factory_sub)
    _add_gates_parser(factory_sub)
    _add_dashboard_parser(factory_sub)


def _cmd_gates(args: argparse.Namespace) -> int:
    from zyko.factory.gates import combined_gates_text, run_all_gates

    gates = run_all_gates(max_seconds=args.max_seconds)
    print(combined_gates_text(gates))
    code = EXIT_OK if all(g.ok for _, g in gates) else EXIT_FINDINGS
    return _write_dashboard_outputs(args, gates, code)


def _dashboard_input(gates: list[tuple[str, Any]]) -> Any:
    """حوّل بوابات المراحل الأربع إلى مدخل لوحة التحكم — بلا توقيت (يكسر الحتمية)."""
    from zyko.dashboard import DashboardInput, GateResult
    from zyko.version import __version__

    rows = tuple(
        GateResult(
            name=label,
            passed=bool(g.ok),
            reason_ar=f"{sum(1 for r in g.rows if r.passed)}/{len(g.rows)} بوابات",
        )
        for label, g in gates
    )
    return DashboardInput("ZYKO", __version__, rows)


def _write_dashboard_outputs(
    args: argparse.Namespace,
    gates: list[tuple[str, Any]],
    code: int,
) -> int:
    """اكتب لوحة HTML/Markdown عند طلب --html/--md — كود الخروج يعكس البوابات فقط."""
    html_path = getattr(args, "html", None)
    md_path = getattr(args, "md", None)
    if not html_path and not md_path:
        return code
    from pathlib import Path

    from zyko.dashboard import build_dashboard, build_markdown

    data = _dashboard_input(gates)
    if html_path:
        Path(html_path).write_text(build_dashboard(data), encoding="utf-8")
    if md_path:
        Path(md_path).write_text(build_markdown(data), encoding="utf-8")
    parts = [
        f"HTML={html_path}" if html_path else "",
        f"Markdown={md_path}" if md_path else "",
    ]
    print("كُتبت لوحة التحكم — " + " · ".join(p for p in parts if p))
    return code


def _add_dashboard_parser(sub: Any) -> None:
    p = sub.add_parser(
        "dashboard",
        help="لوحة تحكم عربية حتمية (HTML + Markdown) لبوابات المراحل الأربع",
    )
    p.add_argument("--html", default=None, help="اكتب اللوحة (HTML) إلى هذا الملف")
    p.add_argument("--md", default=None, help="اكتب اللوحة (Markdown) إلى هذا الملف")
    p.add_argument("--max-seconds", type=float, default=5.0, help="ميزانية الأداء لكل بوابة")


def _cmd_dashboard(args: argparse.Namespace) -> int:
    if not getattr(args, "html", None) and not getattr(args, "md", None):
        print("حدّد هدفًا واحدًا على الأقل: --html مسار أو --md مسار")
        return EXIT_USAGE
    from zyko.factory.gates import run_all_gates

    gates = run_all_gates(max_seconds=args.max_seconds)
    code = EXIT_OK if all(g.ok for _, g in gates) else EXIT_FINDINGS
    return _write_dashboard_outputs(args, gates, code)


def handle_factory(args: argparse.Namespace) -> int:
    """وجّه أمر المصنع — التفويض حرفي لوحدات المحرك (سلوك واحد بلا انحراف)."""
    command = getattr(args, "factory_cmd", None) or "map"
    if command == "map":
        print(factory_map_text())
        return EXIT_OK
    if command == "fix":
        from zyko.fixer.__main__ import cmd_fix

        return cmd_fix(args)
    if command == "pipeline":
        from zyko.pipeline.__main__ import cmd_run

        return cmd_run(args)
    if command == "workspace":
        from zyko.workspace.__main__ import cmd_run

        return cmd_run(args)
    if command == "baseline":
        from zyko.baseline.__main__ import (
            cmd_check,
            cmd_show,
            cmd_update,
        )

        sub = getattr(args, "baseline_cmd", None)
        if sub == "update":
            return cmd_update(args)
        if sub == "check":
            return cmd_check(args)
        if sub == "show":
            return cmd_show(args)
        print(factory_map_text())
        return EXIT_USAGE
    if command == "gates":
        return _cmd_gates(args)
    if command == "dashboard":
        return _cmd_dashboard(args)
    print(factory_map_text())
    return EXIT_OK


def build_standalone_parser() -> argparse.ArgumentParser:
    """مفسّر مستقل لـ ``python -m zyko.factory`` — نفس الأوامر الفرعية."""
    parser = argparse.ArgumentParser(
        prog="python -m zyko.factory",
        description="بوابة المصنع الموحدة — كل وحدات المحرك الحتمي من باب واحد",
    )
    sub = parser.add_subparsers(dest="factory_cmd")
    register_to(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_standalone_parser().parse_args(argv)
    return handle_factory(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
