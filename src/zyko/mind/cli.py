"""zyko.mind.cli — بوابة الحلقة الإدراكية على سطر الأوامر (عقد المصنع نفسه).

أكواد الخروج — اصطلاح المراحل نفسه:
  0 الحلقة مقبولة كاملة (كل البوابات خضراء)
  1 الحلقة مرفوضة عند بوابة (خطة/نقد/تحسين)
  2 فشل هيكلي آمن (مدخلات عدائية أو فشل تنفيذ)

أوامر ثلاثة:
  ``run``     — ``zyko mind "الهدف" -o مجلد``: إدراك ← خطة ← تنفيذ ← نقد ←
              تحسين ← ذاكرة، بإيصال حتمي يُكتب في ``<out>/.zyko/mind/``
              ويُطبَع ملخصه على الطرفية بنفس نسق بوابات المستودع.
  ``map``     — خريطة العقل المستقل نص ثابت.
  ``memory``  — الذاكرة العابرة للجلسات: دفتر موقّع ودروس عابرة للمشاريع،
              بتدقيق يعاد حسابه من الرأس (سلسلة مكسورة = خروج 1).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from zyko.mind.autodetect import EXPLICIT_CHOICES, CoreDecision, select_core
from zyko.mind.global_memory import GlobalMemory
from zyko.mind.loop import DEFAULT_FAIL_UNDER, DEFAULT_ROUNDS, MindLoop
from zyko.version import __version__

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

_LINE = "-" * 60


def mind_map_text() -> str:
    """خريطة العقل المستقل — نص ثابت حتمي."""
    return "\n".join(
        [
            f"نواة العقل المستقل zyko mind v{__version__} — الحلقة الإدراكية الكاملة",
            "=" * 62,
            "الوحدة     الأمر                              ماذا تفعل",
            "إدراك      داخلي (حتمي)                       تطبيع ← تصنيف ← معايير نجاح",
            "تخطيط      داخلي (بوابة PII←RTL)              خطوات حتمية + استشارة القلب",
            "القلب      تلقائي من البيئة (--brain auto)     مفاتيح سحابية أو Ollama أو حتمي",
            "تنفيذ      محرك الحلقة أو المحدّد              تفويض حرفي لمحركات المصنع",
            "نقد        داخلي (حتمي على القرص)             معايير النجاح على الناتج الفعلي",
            "تحسين      FixerEngine + أدوات معزولة (--tools) إصلاح موثق + اختبارات حقيقية",
            "أدوات      جلسة بعقد صلاحيات وسجل تدقيق        patch_file وrun_tests موقّعة",
            "ذاكرة      <out>/.zyko/mind/                  حالة دائمة + دروس مستخلصة",
            "الذاكرة العابرة  zyko mind memory               دفتر موقّع + دروس عابرة للمشاريع",
            "-" * 62,
            "أكواد الخروج: 0 مقبول · 1 مرفوض عند بوابة · 2 فشل هيكلي آمن",
            "أمثلة:",
            '  zyko mind "انشئ مشروع قائمة مهام مع واجهة سطر أوامر" -o ./جديد',
            '  zyko mind "اصلح الملف src/app.py" -o ./جلسة --dry-run   # تشغيل جاف',
            '  zyko mind "انشئ مشروع ملاحظات مع اختبارات" -o ./ن --rounds 2',
            '  zyko mind memory --json   # الذاكرة العابرة: دفتر موقّع + تدقيق من الرأس',
        ]
    )


def register_to(sub: argparse._SubParsersAction) -> None:
    """سجّل الأمرين الفرعيين: ``run`` و``map`` — نسق ``zyko ai`` نفسه.

    لا ``set_defaults(func)`` هنا — التوجيه عقد ``handle_mind`` عبر
    ``args.mind_cmd``، تمامًا كعقد ``handle_ai`` فوق ``args.ai_cmd``.
    """
    p = sub.add_parser("run", help="شغّل الحلقة الإدراكية كاملة على هدف عربي")
    p.add_argument("goal", help="الهدف العربي — بناء أو إصلاح أو فحص")
    p.add_argument("-o", "--out", required=True, help="مجلد الإخراج (جديد وفارغ)")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--fail-under", type=int, default=DEFAULT_FAIL_UNDER)
    p.add_argument(
        "--brain",
        choices=("auto",) + EXPLICIT_CHOICES,
        default="auto",
        help="القلب: auto كشف تلقائي من البيئة (افتراضي)، أو deterministic، أو مزود سحابي، أو ollama المحلي",
    )
    p.add_argument(
        "--model", default=None, help="اسم النموذج (يغلب الافتراضي) — مثال: qwen-plus أو qwen2.5:7b"
    )
    p.add_argument("--dry-run", action="store_true", help="تشغيل جاف — توثيق بلا كتابة")
    p.add_argument(
        "--tools",
        action="store_true",
        help="تفعيل الأدوات المعزولة: جولة التحسين تشغّل اختبارات حقيقية بسجل تدقيق",
    )
    p.add_argument("--json", action="store_true", help="طباعة الإيصال JSON كاملًا")

    sub.add_parser("map", help="خريطة العقل المستقل (نص ثابت)")

    p = sub.add_parser("memory", help="اعرض الذاكرة العابرة للجلسات — دفتر موقّع ودروس عابرة")
    p.add_argument("--json", action="store_true", help="طباعة الخلاصة JSON حتميًا")
    p.add_argument(
        "--home",
        default=None,
        help="مجلد الذاكرة (افتراضي: ZYKO_DATA_DIR/mind حسب المنصة)",
    )


def handle_mind(args: Any) -> int:
    """وجّه أوامر العقل المستقل — نفس عقد ``handle_ai`` وأكواد الخروج."""
    command = getattr(args, "mind_cmd", None) or "map"
    if command == "map":
        return handle_mind_map(args)
    if command == "run":
        return handle_mind_run(args)
    if command == "memory":
        return handle_mind_memory(args)
    print(f"أمر mind غير معروف: {command}", file=sys.stderr)
    return EXIT_USAGE


def handle_mind_map(_args: Any) -> int:
    """اطبع خريطة العقل — بلا عمل وبلا شبكة."""
    print(mind_map_text())
    return EXIT_OK


def handle_mind_memory(args: Any) -> int:
    """اعرض الذاكرة العابرة للجلسات — تدقيق موثق لا عرض حدسي.

    الخلاصة حتمية بلا أي زمن، والتحقق يعاد حسابه من الرأس هنا —
    سلسلة مكسورة تجعل الخروج 1 (بوابة تدقيق فاشلة) لا تحذيرًا صامتًا.
    """
    home = getattr(args, "home", None)
    memory = GlobalMemory(home) if home else GlobalMemory()
    data = memory.summary()
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("الذاكرة العابرة للجلسات zyko mind memory")
        print(_LINE)
        print(f"المسار: {data['home']}")
        print(f"الجلسات الموثقة: {data['sessions']} (مكتملة بلا فجوات: {data['sessions_ok']})")
        print(f"الدروس العابرة للمشاريع: {data['lessons']}")
        print(f"آخر جلسة: seq={data['last_seq']} — {data['last_outcome_ar'] or 'لا جلسات بعد'}")
        verdict = "سلسلة سليمة ✅" if data["verify_ok"] else f"سلسلة مكسورة ❌ — {data['verify_reason_ar']}"
        print(f"تدقيق الدفتر: {verdict}")
        if data["lessons"]:
            print(_LINE)
            for index, lesson in enumerate(memory.load_lessons()[:10], start=1):
                print(f"{index}. {lesson}")
    return EXIT_OK if data["verify_ok"] else EXIT_FINDINGS


def handle_mind_run(args: Any) -> int:
    """شغّل الحلقة كاملة واطبع ملخص البوابات — بنسق المستودع الحرفي.

    القلب يُختار هنا ذاتيًا (``select_core``): مفاتيح البيئة أو نقطة
    Ollama تفعّل دماغًا حقيقيًا بلا علم، وغيابها يعيد الحتمي — والقرار
    يطبع ويُوثّق في الإيصال. التجاوز الصريح غير الصالح خطأ استخدام (2).
    """
    rounds = int(getattr(args, "rounds", 2) or 2)
    fail_under = int(getattr(args, "fail_under", 75) or 75)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        decision: CoreDecision = select_core(
            explicit=getattr(args, "brain", None),
            model=getattr(args, "model", None),
        )
    except ValueError as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return EXIT_USAGE
    tools_session = None
    if getattr(args, "tools", False):
        from zyko.sandbox.audit import AuditLog
        from zyko.sandbox.contracts import PermissionContract
        from zyko.sandbox.session import ToolSession

        out_root = Path(args.out).absolute()
        contract = PermissionContract.for_roots(out_root, allow_run_tests=True)
        tools_session = ToolSession(
            contract, AuditLog(out_root / ".zyko" / "tools" / "audit.jsonl")
        )
    loop = MindLoop(
        decision.core,
        rounds=rounds,
        fail_under=fail_under,
        core_decision=decision,
        tools=tools_session,
    )
    receipt = loop.run(args.goal, Path(args.out), write=not dry_run)

    if getattr(args, "json", False):
        print(receipt.to_json())
    else:
        print("الحلقة الإدراكية zyko mind — الهدف:", receipt.goal)
        print(_LINE)
        print(f"القلب المُختار: {decision.selected} ({decision.mode}) — {decision.reason_ar}")
        for step in receipt.steps:
            state = "نجاح" if step.ok else "فشل"
            print(f"{step.title_ar:<42} {state:<6} {step.details_ar}")
        print(_LINE)
        verdict = (
            "الحلقة مقبولة ✅" if receipt.ok else f"الحلقة مرفوضة ❌ — عند «{receipt.failed_step}»"
        )
        print(
            f"الخلاصة: {sum(1 for s in receipt.steps if s.ok)}/{len(receipt.steps)} بوابة ناجحة"
            f" — جولات {receipt.rounds_ran}/{receipt.rounds} — الحكم: {verdict}"
        )
        print(f"سلسلة الأدلة: {receipt.chain_hash[:16]}…")
        if receipt.lessons_learned:
            print(f"دروس مكتسبة: {len(receipt.lessons_learned)} — في .zyko/mind/")
        if receipt.reflections:
            print(
                f"انعكاسات موثقة: {len(receipt.reflections)}"
                f" — ميزانية مستهلكة {receipt.budget.get('total_used', 0)}"
                f"/{receipt.budget.get('total_cap', 0)}"
            )
    return EXIT_OK if receipt.ok else EXIT_FINDINGS


def main(argv: Sequence[str] | None = None) -> int:
    """نقطة دخول ``python -m zyko.mind`` — بلا أي استثناء خارج."""
    parser = argparse.ArgumentParser(prog="zyko.mind", description="الحلقة الإدراكية الكاملة")
    register_to(parser.add_subparsers(dest="mind_cmd"))
    args = parser.parse_args(argv)
    return int(handle_mind(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
