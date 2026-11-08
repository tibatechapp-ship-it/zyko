"""واجهة سطر الأوامر لـ zyko.coder — يعمل مباشرة على Termux.

الأوامر:
  plan   : معاينة مخطط من وصف عربي (بلا كتابة)
  new    : معاينة → موافقة → توليد (+ git + فحص)
  check  : فحص حتمي لمجلد مشروع مولَّد
  gate   : بوابة قبول المرحلة 1 (10 أوصاف عربية)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .gate import run_acceptance_gate
from .generate import build_all_files, materialize
from .heuristics import draft_plan
from .plan import PlanValidationError, ProjectPlan, safe_slug
from .precheck import check_source_tree, full_gate

_APPROVAL_WORDS = {"y", "yes", "ن", "نعم", "نعمy", "1"}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zyko-coder",
        description="توليد مشاريع حتمي من وصف عربي — مخطط متحقق ثم فحص قبل التسليم",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("plan", help="اعرض مسوّدة المخطط من وصف عربي (بلا كتابة)")
    q.add_argument("description", help="الوصف العربي للمشروع")
    q.add_argument("--json", action="store_true", help="اطبع المخطط JSON")

    n = sub.add_parser("new", help="توليد مشروع: مخطط → موافقة → كتابة → فحص")
    n.add_argument("--plan", "-p", required=True, help="الوصف العربي للمشروع")
    n.add_argument("--out", "-o", default=None, help="مجلد الإخراج (افتراضي: ./<name>)")
    n.add_argument("--name", default=None, help="تجاوز اسم المشروع")
    n.add_argument(
        "--template",
        choices=["python-cli", "fastapi-api", "static-site"],
        default=None,
        help="تجاوز القالب",
    )
    n.add_argument("--yes", "-y", action="store_true", help="موافقة دون سؤال")
    n.add_argument("--no-git", action="store_true", help="بلا git init/commit")
    n.add_argument("--run-tests", action="store_true", help="شغّل اختبارات المشروع بعد التوليد")

    c = sub.add_parser("check", help="فحص حتمي لمجلد مشروع")
    c.add_argument("path", help="مجلد المشروع المولَّد")
    c.add_argument("--run-tests", action="store_true", help="شغّل اختباراته أيضًا")

    g = sub.add_parser("gate", help="بوابة قبول المرحلة 1: 10 أوصاف عربية")
    g.add_argument("--no-tests", action="store_true", help="فحص ثابت فقط بلا pytest")
    return p


def _resolve_plan(args: argparse.Namespace) -> ProjectPlan:
    description = getattr(args, "plan", None) or getattr(args, "description", "")
    plan = draft_plan(description)
    overrides = {}
    if getattr(args, "name", None):
        overrides["name"] = safe_slug(args.name, fallback=plan.name)
    if getattr(args, "template", None):
        overrides["template"] = args.template
    if overrides:
        data = plan.to_dict() | overrides
        plan = ProjectPlan.from_dict(data)
    return plan


def cmd_plan(args: argparse.Namespace) -> int:
    plan = _resolve_plan(args)
    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(plan.summary_ar())
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    try:
        plan = _resolve_plan(args)
    except PlanValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # بوابة الموافقة: لا كتابة قبل رؤية المخطط وقبوله صراحةً
    print(plan.summary_ar())
    if not args.yes:
        try:
            answer = input("\nهل توافق على هذا المخطط؟ [نعم/y] ")
        except (EOFError, KeyboardInterrupt):
            print("\nأُلغي — لم يُكتب أي ملف")
            return 1
        if answer.strip().lower() not in _APPROVAL_WORDS:
            print("أُلغي — لم يُكتب أي ملف")
            return 1

    out = Path(args.out) if args.out else Path.cwd() / plan.name
    try:
        result = materialize(plan, out, git_init=not args.no_git)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    tree = build_all_files(plan)
    static = check_source_tree(tree)
    print(f"\nوُلّد {len(result.files)} ملفًا في {result.root}")
    if result.git_committed:
        print("git: التزام أول عربي ✓")
    elif result.git_skipped_reason:
        print(f"git: تخطّي ({result.git_skipped_reason})")
    print("RECEIPT.md: ✓ (وصل التوليد)")

    if not static.ok:
        print("\nفحص ثابت: فشل ✗ — المشروع مرفوض:", file=sys.stderr)
        for pr in static.problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1
    print("فحص ثابت (ast + RTL): نظيف ✓")

    if args.run_tests:
        full = full_gate(plan, result.root, run_tests=True)
        if full.problems:
            print("اختبارات المشروع: فشل ✗", file=sys.stderr)
            for pr in full.problems:
                print(f"  - {pr}", file=sys.stderr)
            return 1
        print("اختبارات المشروع: مرّت ✓")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from .precheck import check_directory

    report = check_directory(args.path)
    if report.ok:
        print(f"فحص ثابت: نظيف ✓ ({report.py_files} بايثون، {report.other_files} أخرى)")
    else:
        print("فحص ثابت: مشاكل ✗", file=sys.stderr)
        for pr in report.problems:
            print(f"  - {pr}", file=sys.stderr)
    if args.run_tests:
        from .precheck import run_project_tests

        t = run_project_tests(args.path)
        if t.problems:
            print("اختبارات: فشل ✗", file=sys.stderr)
            for pr in t.problems:
                print(f"  - {pr}", file=sys.stderr)
            return 1
        print("اختبارات: مرّت ✓")
    return 0 if report.ok else 1


def cmd_gate(args: argparse.Namespace) -> int:
    result = run_acceptance_gate(run_tests=not args.no_tests)
    print(result.table_ar())
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {"plan": cmd_plan, "new": cmd_new, "check": cmd_check, "gate": cmd_gate}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
