"""zyko.ai.cli — بوابة طبقة الذكاء على سطر الأوامر (نفس عقد المصنع).

أكواد الخروج — اصطلاح المراحل نفسه:
  0 جلسة مقبولة (أو الخريطة/البوابة نجحت)
  1 جلسة مرفوضة عند بوابة (خطة/درجة/حارس)
  2 خطأ استخدام أو فشل هيكلي آمن
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from zyko.ai.gate import run_phase8_gate
from zyko.version import __version__

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def ai_map_text() -> str:
    """خريطة طبقة الذكاء — نص ثابت حتمي."""
    return "\n".join(
        [
            f"طبقة الذكاء zyko AI v{__version__} — فوق آلة حتمية قابلة للتحقق",
            "=" * 62,
            "العقل/الأمر                                  ماذا يفعل",
            "planner      zyko ai run --goal «وصف»       مخطط حتمي مقيّد بالبوابات (بلا نموذج وبلا شبكة)",
            "ollama       zyko ai run --brain ollama …   نموذج محلي حقيقي خلف البوابات نفسها (يتطلب Ollama)",
            "qwen         zyko ai run --brain qwen …     نموذج Qwen عبر واجهة متوافقة مع OpenAI خلف البوابات نفسها (يتطلب ZYKO_QWEN_API_KEY)",
            "bestof       zyko ai run --brain bestof …   منافسة عقول: النموذج أولًا ثم المخطط — أول مقبول يفوز",
            "gated:<اسم>  —                              أي عقل آخر يُمرّ عبر بوابات المصنع نفسها",
            "-" * 62,
            "مسار الجلسة: اقتراح العقل ← بوابة PII ← بوابة RTL ← توليد (حلقة",
            "مراجعة←إصلاح) ← خط أساس (تسجيل←فحص) ← إيصال موقّع بالبصمات",
            "البوابات: PII رفض قاطع · RTL رفض الأخطاء · الدرجة ≥ الحد · لا تراجع",
            "-" * 62,
            "أكواد الخروج: 0 مقبول · 1 مرفوض عند بوابة · 2 فشل هيكلي آمن",
            "أمثلة:",
            '  python -m zyko.ai run --goal "قائمة مهام" --out ./جديد',
            "  python -m zyko.ai run --goal «وصف» --out ./ج --dry-run   # بلا كتابة",
            "  python -m zyko.ai run --brain ollama --model qwen2.5:7b …  # عقل محلي حقيقي",
            "  python -m zyko.ai run --brain qwen --model qwen-plus …     # عقل Qwen السحابي خلف البوابات نفسها",
            "  python -m zyko.ai run --brain bestof --model qwen2.5:7b …  # النموذج أولًا والمخطط يحتاط",
            "  python -m zyko.ai ollama                                 # فحص خادم Ollama",
            "  python -m zyko.ai gate                                   # بوابة المرحلة 8",
        ]
    )


def _build_session(args: Any) -> Any:
    """ابنِ الجلسة حسب اختيار العقل — ``planner`` الافتراضي، و``ollama`` العقل المحلي.

    العقل المحلي يُغلَّف بـ ``GatedBrain`` دائمًا: نص النموذج لا يُقبل
    قبل بوابة PII وبوابة RTL — العقل يضيف، والبوابات تقرّر.
    و``bestof`` يوسّع المنافسة: النموذج المحلي أولًا فالمخطط الحتمي
    احتياطًا — كل مرشح خلف بواباته، وأول مقبول يفوز (البوابات تحكم
    بين العقول لا بين النصوص فقط).
    """
    from zyko.ai.brains import GatedBrain, PlannerBrain
    from zyko.ai.session import AISession

    brain_choice = getattr(args, "brain", "planner") or "planner"
    if brain_choice == "ollama":
        from zyko.ai.ollama_brain import OllamaBrain

        brain = GatedBrain(OllamaBrain(model=args.model, host=getattr(args, "ollama_host", None)))
    elif brain_choice == "qwen":
        from zyko.ai.qwen_brain import QwenBrain

        brain = GatedBrain(QwenBrain(model=args.model, host=getattr(args, "qwen_host", None)))
    elif brain_choice == "bestof":
        from zyko.ai.best_of_brain import BestOfBrain
        from zyko.ai.ollama_brain import OllamaBrain

        brain = GatedBrain(
            BestOfBrain(
                [
                    OllamaBrain(model=args.model, host=getattr(args, "ollama_host", None)),
                    PlannerBrain(),
                ]
            )
        )
    else:
        brain = GatedBrain(PlannerBrain())
    return AISession(brain=brain, rounds=args.rounds, fail_under=args.fail_under)


def handle_ai(args: Any) -> int:
    """وجّه أوامر طبقة الذكاء — نفس عقد أكواد الخروج."""
    command = getattr(args, "ai_cmd", None) or "map"
    if command == "map":
        print(ai_map_text())
        return EXIT_OK

    if command == "run":
        if getattr(args, "brain", "planner") in ("ollama", "bestof", "qwen") and not getattr(
            args, "model", None
        ):
            print(
                f"خطأ: --brain {getattr(args, 'brain', 'planner')} يتطلب --model — مثال: --model qwen2.5:7b أو qwen-plus",
                file=sys.stderr,
            )
            return EXIT_USAGE
        out = Path(args.out)
        write = not getattr(args, "dry_run", False)
        session = _build_session(args)
        receipt = session.run(args.goal, out, write=write)
        if out.exists():
            session.write_receipt(receipt, out)
        if args.format == "json":
            print(receipt.to_json(include_timing=args.include_timing), end="")
        elif args.format == "summary":
            print(
                f"{receipt.verdict_ar()} — خطوات {len(receipt.steps)}، "
                f"أدنى درجة {receipt.min_score_after}، ملفات {len(receipt.files_written)}"
            )
        else:
            print(receipt.to_md())
        if receipt.ok:
            return EXIT_OK
        return EXIT_USAGE if receipt.failed_step in ("goal", "out") else EXIT_FINDINGS

    if command == "ollama":
        from zyko.ai.ollama_brain import DEFAULT_HOST, HOST_ENV, list_models

        host = (
            getattr(args, "ollama_host", None) or os.environ.get(HOST_ENV) or DEFAULT_HOST
        ).rstrip("/")
        try:
            models = list_models(host)
        except Exception:
            print(f"Ollama على {host} — غير متاح ❌")
            print("ثبّت Ollama وشغّل الخادم (ollama serve) ثم أعد المحاولة.")
            return EXIT_FINDINGS
        print(f"Ollama على {host} — متاح ✅")
        if models:
            print(f"النماذج ({len(models)}): " + "، ".join(models))
        else:
            print("لا نماذج مثبتة بعد — اسحب نموذجًا مثل: ollama pull qwen2.5:7b")
        return EXIT_OK

    if command == "gate":
        gates = run_phase8_gate(max_seconds=args.max_seconds)
        print(gates.table_ar())
        return EXIT_OK if gates.ok else EXIT_FINDINGS

    print(ai_map_text())
    return EXIT_OK


def register_to(sub: Any) -> None:
    """ثبّت أوامر طبقة الذكاء في حاوية subparsers القائمة.

    نفس نمط المصنع: الحاوية تُمرَّر إلينا جاهزة (من ``zyko ai`` أو من
    ``python -m zyko.ai``) ونضيف الأوامر فيها مباشرة — بلا مستوى وهمي.
    """
    sub.add_parser("map", help="خريطة الطبقة: العقول والبوابات ومسار الجلسة")
    run_p = sub.add_parser("run", help="جلسة موثّقة: هدف عربي ⇒ مشروع عبر البوابات")
    run_p.add_argument("--goal", required=True, help="الهدف: وصف عربي للمشروع المطلوب")
    run_p.add_argument("--out", required=True, help="مجلد الإخراج (يجب أن يكون جديدًا وفارغًا)")
    run_p.add_argument(
        "--rounds", type=int, default=1, help="جولات مراجعة←إصلاح (0 مراجعة فقط، السقف 3)"
    )
    run_p.add_argument(
        "--fail-under",
        type=int,
        default=75,
        help="حد القبول: أدنى درجة بعد الإصلاح ≥ هذا الحد (الافتراضي 75)",
    )
    run_p.add_argument(
        "--brain",
        choices=("planner", "ollama", "qwen", "bestof"),
        default="planner",
        help="العقل: planner الحتمي (افتراضي)، أو ollama النموذج المحلي، أو qwen السحابي المتوافق مع OpenAI، أو bestof منافسة عقول (النموذج ثم المخطط)",
    )
    run_p.add_argument(
        "--model",
        default=None,
        help="اسم النموذج (مطلوب مع --brain ollama أو qwen أو bestof) — مثال: qwen2.5:7b أو qwen-plus",
    )
    run_p.add_argument(
        "--ollama-host",
        default=None,
        help="عنوان خادم Ollama (افتراضي http://127.0.0.1:11434 أو ZYKO_OLLAMA_HOST)",
    )
    run_p.add_argument(
        "--qwen-host",
        default=None,
        help="عنوان نقطة نهاية Qwen المتوافقة مع OpenAI (افتراضي DashScope أو ZYKO_QWEN_HOST)؛ المفتاح من ZYKO_QWEN_API_KEY",
    )
    run_p.add_argument("--dry-run", action="store_true", help="لا تكتب شيئًا على القرص")
    run_p.add_argument("--format", choices=("json", "text", "summary"), default="text")
    run_p.add_argument(
        "--include-timing", action="store_true", help="أضف الزمن (يكسر الحتمية البايتية)"
    )
    ollama_p = sub.add_parser(
        "ollama", help="فحص خادم Ollama المحلي: هل يعمل؟ وما النماذج المتاحة؟"
    )
    ollama_p.add_argument(
        "--ollama-host",
        default=None,
        help="عنوان الخادم (افتراضي http://127.0.0.1:11434 أو ZYKO_OLLAMA_HOST)",
    )
    gate_p = sub.add_parser("gate", help="بوابة المرحلة 8 — 12 بوابة على 3 مراسئ")
    gate_p.add_argument("--max-seconds", type=float, default=5.0, help="سقف زمن كل جلسة دليل")


def build_standalone_parser() -> argparse.ArgumentParser:
    """مفسّر مستقل لـ ``python -m zyko.ai`` — نفس الأوامر الفرعية."""
    parser = argparse.ArgumentParser(
        prog="python -m zyko.ai",
        description="طبقة الذكاء فوق المصنع — جلسات موثّقة عبر البوابات القابلة للتحقق",
    )
    sub = parser.add_subparsers(dest="ai_cmd")
    register_to(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_standalone_parser().parse_args(argv)
    return handle_ai(args)


if __name__ == "__main__":
    sys.exit(main())
