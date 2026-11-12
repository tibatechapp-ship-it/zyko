"""CLI المُقترِح الحتمي — أكواد خروج صادقة: 0 مُركَّب / 1 لا فائز / 2 عقد رديء.

python -m zyko.tools.synth --spec task.py
python -m zyko.tools.synth --spec task.py --json receipt.json --max-nodes 6
cat task.py | python -m zyko.tools.synth --stdin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zyko.tools.synth.engine import EXIT_NOT_FOUND, EXIT_SPEC_BAD, EXIT_SYNTHESIZED, run

_EXIT_BY_VERDICT = {
    "synthesized": EXIT_SYNTHESIZED,
    "exhausted": EXIT_NOT_FOUND,
    "budget": EXIT_NOT_FOUND,
    "invalid_spec": EXIT_SPEC_BAD,
    "unverifiable": EXIT_SPEC_BAD,
}

_TAG_BY_VERDICT = {
    "synthesized": "مُركَّب ومُحكَم",
    "exhausted": "الفضاء استُنفد — برهان غياب داخل الصنف",
    "budget": "الميزانية قطعت البحث — غير مكتمل بصدق",
    "invalid_spec": "عقد المهمة مرفوض",
    "unverifiable": "تعذّر التحقق",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zyko.tools.synth",
        description=(
            "المُقترِح الحتمي: تركيب برنامج من عقود معلنة بالبحث المغلق — بلا شبكة وبلا نموذج لغوي"
        ),
    )
    parser.add_argument("--spec", default=None, help="مسار ملف عقد المهمة")
    parser.add_argument("--stdin", action="store_true", help="اقرأ العقد من المدخل القياسي")
    parser.add_argument("--json", default=None, help="اكتب الإيصال الحتمي في ملف")
    parser.add_argument("--max-nodes", type=int, default=None, help="سقف عقد التعبير (1-8)")
    parser.add_argument("--budget", type=int, default=None, help="ميزانية المرشحين")
    parser.add_argument("--block-beam", type=int, default=None, help="سقف إسهام الكتلة الواحدة")
    args = parser.parse_args(argv)

    if args.stdin:
        source = sys.stdin.read()
    elif args.spec:
        try:
            source = Path(args.spec).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"❌ لا يمكن قراءة العقد: {exc}", file=sys.stderr)
            return EXIT_SPEC_BAD
    else:
        parser.error("حدّد --spec مساراً أو استخدم --stdin")
        return EXIT_SPEC_BAD  # pragma: no cover — error() يخرج بنفسه

    kwargs: dict[str, int] = {}
    if args.max_nodes is not None:
        kwargs["max_nodes"] = args.max_nodes
    if args.budget is not None:
        kwargs["budget"] = args.budget
    if args.block_beam is not None:
        kwargs["block_beam"] = args.block_beam

    receipt = run(source, **kwargs)

    if args.json:
        Path(args.json).write_text(receipt.to_json() + "\n", encoding="utf-8")
    tag = _TAG_BY_VERDICT.get(receipt.verdict, receipt.verdict)
    print(
        f"[المُقترِح الحتمي] {tag}: مهمة {receipt.task}, "
        f"مُعدَّد = {receipt.emitted}, مُختبَر = {receipt.tried}"
    )
    if receipt.winner_expr:
        print(f"  الفائز: {receipt.winner_expr}")
    print(f"  {receipt.reason_ar}")
    print(f"  بصمة السلسلة: {receipt.chain_hash[:16]}…")
    return _EXIT_BY_VERDICT.get(receipt.verdict, EXIT_SPEC_BAD)


if __name__ == "__main__":
    sys.exit(main())
