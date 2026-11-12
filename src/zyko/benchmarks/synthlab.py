"""zyko.benchmarks.synthlab — معمل المُقترِح الحتمي: البرمجة بلا نموذج لغوي.

هذه العدّة تجيب سؤال الجولة 15 بالأرقام: **هل يكتب zyko برامج صحيحة
بلا شبكة وبلا نموذج لغوي؟** كل حالة عقد مهمة واحد يُقرأ ويُبحث
ويُحكَم عبر ``zyko.tools.synth`` الحتمي 100%، والحكم على ثلاث
فئات صادقة:

1. **فئة التركيب الحقيقي (synthesized)** — عقد قابل للإرضاء داخل
   الصنف المعلن: يجب أن يعود الفائز محكوماً من الحاكم الشكلي،
   ومصدره ينفّذ فعلاً على نقاط المجال.
2. **فئة برهان الغياب (exhausted)** — عقد يستحيل إرضاؤه داخل النحو
   المغلق: يجب أن يعود البرهان بغياب صريح — لا فائز، ولا ميزانية
   قطعت البحث، وإنما استنفاد كامل للفضاء المعلن.
3. **فئة الحدود الصادقة (invalid/unverifiable/budget)** — عقد رديء
   أو غير قابل للتحقق أو فضاء أوسع من ميزانية معلنة: الحكم الثلاثي
   للقارئ أو انقطاع البحث المعلن — بصدق لا بافتراض.

القواعد الصارمة كما في المستودع كله:

* **حتمية بالبايت (P6)** — نفس العدّة ⇒ نفس الإيصال بالبايت،
  وبصمة سلسلة sha256 فوق (المعرّف + الحكم + الفائز).
* **فشل صادق** — أي حالة لا تطابق توقع فئتها تعود صفًا فاشلاً
  بمشكلة عربية صريحة؛ لا يُخفى ولا يُعتذر عنه.
* **النموذج المزيّف ممنوع هنا** — هذه الطبقة بلا أي استدعاء نموذج:
  نحو مُغلق، تنفيذ مبيّض، وحاكم شكلي — هذا هو المقاس.

    from zyko.benchmarks.synthlab import run_synth_lab

    report = run_synth_lab()
    assert report.ok
    print(report.table_ar())
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from zyko.tools.synth.engine import SynthReceipt, run

LAB_KIND = "zyko.synthlab.report"

CAT_SYNTH = "synthesized"
CAT_EXHAUST = "exhausted"
CAT_HONEST = "honest-limit"

# أسماء الفئات كما تظهر في الجدول العربي
CATEGORY_LABELS: dict[str, str] = {
    CAT_SYNTH: "التركيب الحقيقي",
    CAT_EXHAUST: "برهان الغياب",
    CAT_HONEST: "الحدود الصادقة",
}

CATEGORY_ORDER: tuple[str, ...] = (CAT_SYNTH, CAT_EXHAUST, CAT_HONEST)


@dataclass(frozen=True)
class SynthCase:
    """حالة معمل واحدة — عقد مهمة وتوقع صادق محكم."""

    case_id: str
    category: str
    title_ar: str
    source: str
    expect_verdict: str
    expect_winner: str | None = None
    max_nodes: int | None = None
    budget: int | None = None


@dataclass(frozen=True)
class SynthLabReport:
    """تقرير المعمل — حتمي بالبايت، بلا أزمنة."""

    total: int
    passed: int
    failed: int
    by_category: dict[str, dict[str, object]]
    rows: tuple[dict[str, object], ...]
    chain_hash: str
    ok: bool
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "by_category": self.by_category,
            "chain_hash": self.chain_hash,
            "failed": self.failed,
            "kind": LAB_KIND,
            "ok": self.ok,
            "passed": self.passed,
            "rows": list(self.rows),
            "total": self.total,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def table_ar(self) -> str:
        lines = ["----------------------------------------------"]
        lines.append(f"{'الفئة':<28}{'العدد':>7}{'ناجح':>7}{'النسبة':>9}")
        lines.append("----------------------------------------------")
        for cat in CATEGORY_ORDER:
            stats = self.by_category[cat]
            lines.append(
                f"{CATEGORY_LABELS[cat]:<28}{stats['total']:>7}"
                f"{stats['passed']:>7}{stats['rate']:>8.1f}%"
            )
        lines.append("----------------------------------------------")
        tag = "✅ العدّة تجتاز عقودها" if self.ok else "❌ حالات فاشلة — انظر rows"
        lines.append(
            f"الإجمالي: {self.passed}/{self.total} — بصمة السلسلة: {self.chain_hash[:16]}… — {tag}"
        )
        return "\n".join(lines)


def _S(
    name: str,
    task_ar: str,
    requires: tuple[str, ...],
    ensures: tuple[str, ...],
    domains: dict[str, str],
) -> str:
    """ابنِ مصدر عقد مهمة موحد الشكل — توجيهات فوق التعريف حصراً."""
    lines = [f"# zyko:task: {task_ar}"]
    lines += [f"# zyko:requires: {r}" for r in requires]
    lines += [f"# zyko:ensures: {e}" for e in ensures]
    lines += [f"# zyko:domain: {dname} = {dval}" for dname, dval in domains.items()]
    params = ", ".join(domains.keys())
    lines.append(f"def {name}({params}):")
    lines.append("    raise NotImplementedError")
    return "\n".join(lines) + "\n"


def _cases() -> tuple[SynthCase, ...]:
    """العدّة التعاقدية — 60 حالة بأرقام ثابتة بالبايت."""
    cases: list[SynthCase] = []
    n = 0

    def case(
        category: str,
        title: str,
        source: str,
        expect: str,
        winner: str | None = None,
        *,
        max_nodes: int | None = None,
        budget: int | None = None,
    ) -> None:
        nonlocal n
        n += 1
        cases.append(
            SynthCase(
                case_id=f"S-{n:04d}",
                category=category,
                title_ar=title,
                source=source,
                expect_verdict=expect,
                expect_winner=winner,
                max_nodes=max_nodes,
                budget=budget,
            )
        )

    # ============ فئة التركيب الحقيقي — 30 حالة ============
    case(
        CAT_SYNTH,
        "المضاعفة",
        _S("double", "ضعف المدخل", ("x >= 0",), ("result * 2 == x",), {"x": "range(0, 8)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الثلاثية",
        _S("triple", "ثلاثة أضعاف", ("x >= 0",), ("result == 3 * x",), {"x": "range(0, 8)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "النصف",
        _S("half", "نصف المدخل", ("x >= 0",), ("result * 2 == x",), {"x": "range(0, 8)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الجمع الثابت",
        _S("bump", "أضف خمسة", (), ("result == x + 5",), {"x": "range(0, 8)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الطرح الثابت",
        _S("drop", "اطرح ثلاثة", ("x >= 3",), ("result == x - 3",), {"x": "range(3, 12)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "النقيض",
        _S("negate", "اعكس الإشارة", (), ("result == -x",), {"x": "range(-5, 5)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "القيمة المطلقة",
        _S("absolute", "المسافة من الصفر", (), ("result == abs(x)",), {"x": "range(-5, 5)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "المربع",
        _S("square", "الضرب في نفسه", ("x >= 0",), ("result == x * x",), {"x": "range(0, 9)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "مجموع زوجين",
        _S(
            "plus", "اجمع زوجين", (), ("result == x + y",), {"x": "range(0, 5)", "y": "range(0, 5)"}
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "فرق زوجين",
        _S(
            "minus",
            "اطرح الثاني من الأول",
            (),
            ("result == x - y",),
            {"x": "range(0, 5)", "y": "range(0, 5)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "أكبر زوجين",
        _S(
            "bigger",
            "أكبر عددين",
            (),
            ("result >= x and result >= y and (result == x or result == y)",),
            {"x": "range(0, 8)", "y": "range(0, 8)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "أصغر زوجين",
        _S(
            "smaller",
            "أصغر عددين",
            (),
            ("result <= x and result <= y and (result == x or result == y)",),
            {"x": "range(0, 8)", "y": "range(0, 8)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "التقييد الكامل",
        _S(
            "clamp",
            "احصر بين صفر ومئة",
            (),
            ("(result == x if 0 <= x <= 100 else (result == 0 if x < 0 else result == 100))",),
            {"x": "range(-20, 130)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الحصر السفلي",
        _S(
            "floor0",
            "لا نزول تحت الصفر",
            (),
            ("(result == x if x >= 0 else result == 0)",),
            {"x": "range(-15, 15)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الحصر العلوي",
        _S(
            "cap99",
            "لا تجاوز 99",
            (),
            ("(result == x if x <= 99 else result == 99)",),
            {"x": "range(80, 130)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "التساوي الزوجي",
        _S("is_even", "هل العدد زوجي؟", (), ("result == (x % 2 == 0)",), {"x": "range(0, 6)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الفردية",
        _S("is_odd", "هل العدد فردي؟", (), ("result == (x % 2 != 0)",), {"x": "range(0, 6)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الإيجابية",
        _S("is_positive", "هل العدد موجب؟", (), ("result == (x > 0)",), {"x": "range(-4, 4)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "اللاسالب",
        _S("is_nonneg", "هل العدد غير السالب؟", (), ("result == (x >= 0)",), {"x": "range(-4, 4)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "السلبية",
        _S("is_negative", "هل العدد سالب؟", (), ("result == (x < 0)",), {"x": "range(-4, 4)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "عتبة العشرة",
        _S("over_ten", "هل تجاوز العاشرة؟", (), ("result == (x >= 10)",), {"x": "range(5, 15)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "بين حدّين",
        _S(
            "between",
            "داخل المجال 1..3",
            (),
            ("result == (x >= 1 and x <= 3)",),
            {"x": "range(0, 5)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "القسمة على عشرة",
        _S("tenth", "عُشر العدد", ("x >= 0",), ("result * 10 == x",), {"x": "range(0, 20)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "المئوية",
        _S(
            "percent",
            "المئوية الصحيحة",
            ("y >= 1",),
            ("result == (x * 100) // y",),
            {"x": "range(0, 10)", "y": "range(1, 5)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "التدوير",
        _S("rounded", "العدد مُدوَّراً لنصفه", (), ("result == round(x / 2)",), {"x": "range(0, 10)"}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "طول النص",
        _S("size_of", "طول النص", (), ("result == len(s)",), {"s": '["a", "bb", "ccc", "dddd"]'}),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "ترتيب النصوص",
        _S(
            "sorted_s",
            "النص مرتباً",
            (),
            ("result == sorted(s)",),
            {"s": '["pear", "apple", "fig"]'},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "أصغر نص",
        _S(
            "first_s",
            "النص الأول ترتيباً",
            (),
            ("result == min(s)",),
            {"s": '["pear", "apple", "fig"]'},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "مضاعفة الثاني",
        _S(
            "double_y",
            "ضعف المعامل الثاني",
            (),
            ("result == y * 2",),
            {"x": "range(0, 4)", "y": "range(0, 6)"},
        ),
        "synthesized",
    )
    case(
        CAT_SYNTH,
        "الفرق الموجب",
        _S(
            "gap",
            "المسافة بين عددين",
            (),
            ("(result == x - y if x >= y else result == y - x)",),
            {"x": "range(0, 6)", "y": "range(0, 6)"},
        ),
        "synthesized",
    )

    # ============ فئة برهان الغياب — 12 حالة ============
    case(
        CAT_EXHAUST,
        "صفر لا يساوي واحداً",
        _S("broken0", "عقد مستحيل حسابياً", (), ("result * 0 == 1",), {"x": "range(0, 4)"}),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "تناقض عقدين",
        _S(
            "broken1",
            "يساوي x و x+1 معاً",
            (),
            ("result == x", "result == x + 1"),
            {"x": "range(1, 5)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "أصغر وأكبر من نفسه",
        _S("broken2", "شرطان متضادان", (), ("result < x and result > x",), {"x": "range(0, 4)"}),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "طول عدد صحيح",
        _S(
            "broken3",
            "طول عدد لا يوجد",
            (),
            (
                "result == x",
                "result == len(x)",
            ),
            {"x": "range(2, 5)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "يساوي نقيضه بلا صفر",
        _S(
            "broken4",
            "x يساوي -x خارج الصفر",
            (),
            ("result == x", "result == -x"),
            {"x": "range(1, 5)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "المربع أصغر من الأصل",
        _S(
            "broken5",
            "مربع أقل من الأصل لعدد ≥ 2",
            ("x >= 2",),
            ("result == x * x", "result < x"),
            {"x": "range(2, 6)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "التساوي والاختلاف",
        _S(
            "broken6",
            "يساوي x ولا يساويه",
            (),
            ("result == x", "result != x"),
            {"x": "range(0, 4)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "برج أُس فوق سقف التركيب",
        _S(
            "broken7",
            "مضاعفة برج الأُس فوق سقف العقد",
            (),
            ("result * x == x ** x ** x",),
            {"x": "[2, 3]"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "ثابتان متضادان",
        _S("broken8", "واحد واثنان معاً", (), ("result == 1", "result == 2"), {"x": "range(0, 3)"}),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "الصفر ولا غير الصفر",
        _S(
            "broken9",
            "يساوي الصفر ولا يساويه",
            (),
            ("result == x - x", "result != 0"),
            {"x": "range(1, 4)"},
        ),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "القسمة العقدية على صفر",
        _S("broken10", "لاحق يستحيل بلا استثناء", (), ("result == x / 0",), {"x": "range(1, 4)"}),
        "exhausted",
    )
    case(
        CAT_EXHAUST,
        "المجال خارج المسبقات",
        _S(
            "broken11",
            "مسبق يستحيل على المجال",
            ("x >= 100",),
            ("result == x",),
            {"x": "range(0, 8)"},
        ),
        "exhausted",
    )

    # ============ فئة الحدود الصادقة — 18 حالة ============
    case(CAT_HONEST, "لا دالة هيكلية", "def f(x):\n    return x\n", "invalid_spec")
    case(
        CAT_HONEST,
        "دالتان هيكليتان",
        (
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\n"
            "def f(x):\n    ...\n\n\ndef g(x):\n    ...\n"
        ),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "الناتج معاملاً",
        _S("c3", "result اسم محجوز", (), ("result == 1",), {"result": "[1]"}),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "معامل متغير",
        ("# zyko:ensures: result == 1\ndef f(*args):\n    ...\n"),
        "invalid_spec",
    )
    case(CAT_HONEST, "مصدر لا يُجمَّع", "def f(:\n", "invalid_spec")
    case(
        CAT_HONEST,
        "لاحق لا يُجمَّع",
        ("# zyko:ensures: result == (x + 1\n# zyko:domain: x = [1]\ndef f(x):\n    ...\n"),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "شكل مجال مرفوض",
        ("# zyko:ensures: result == x\n# zyko:domain: x = [1, 2\ndef f(x):\n    ...\n"),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "مجال مكرر",
        (
            "# zyko:ensures: result == x\n"
            "# zyko:domain: x = [1]\n# zyko:domain: x = [2]\n"
            "def f(x):\n    ...\n"
        ),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "مجال لغير معامل",
        ("# zyko:ensures: result == x\n# zyko:domain: y = [1]\ndef f(x):\n    ...\n"),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "مجال فارغ",
        _S("c10", "مجال بلا نقاط", (), ("result == x",), {"x": "range(5, 5)"}),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "لاحق غائب",
        _S("c11", "مسبق بلا لاحق", ("x >= 0",), (), {"x": "range(0, 4)"}),
        "unverifiable",
    )
    case(
        CAT_HONEST,
        "اسم غريب خارج المعاملات",
        _S("c12", "z ليست معاملاً أصلاً", (), ("result == x + z",), {"x": "range(0, 4)"}),
        "invalid_spec",
    )
    case(
        CAT_HONEST,
        "معامل بلا مجال",
        (
            "# zyko:ensures: result == x + z\n# zyko:domain: x = range(0, 4)\n"
            "def f(x, z):\n    ...\n"
        ),
        "unverifiable",
    )
    case(
        CAT_HONEST,
        "سقف عقد فوق الحد",
        _S("c13", "فضاء بسقف غير مسموح", (), ("result == x",), {"x": "range(0, 4)"}),
        "unverifiable",
        max_nodes=9,
    )
    case(
        CAT_HONEST,
        "ميزانية تقطع الجذر",
        _S("c14", "جذر تكعيبي بلا ميزانية كافية", (), ("result * 3 == x",), {"x": "range(0, 6)"}),
        "budget",
        budget=7,
    )
    case(
        CAT_HONEST,
        "ميزانية تقطع الزوجين",
        _S(
            "c16",
            "أكبر زوجين بميزانية ضئيلة",
            (),
            ("result >= x and result >= y and (result == x or result == y)",),
            {"x": "range(0, 8)", "y": "range(0, 8)"},
        ),
        "budget",
        budget=10,
    )
    case(
        CAT_HONEST,
        "ميزانية تقطع التقييد",
        _S(
            "c17",
            "تقييد بميزانية ضئيلة",
            (),
            ("(result == x if 0 <= x <= 100 else (result == 0 if x < 0 else result == 100))",),
            {"x": "range(-20, 130)"},
        ),
        "budget",
        budget=100,
    )
    case(
        CAT_HONEST,
        "ميزانية تقطع عقد الطول",
        _S(
            "c18",
            "طول وحدّ أدنى بميزانية ضئيلة",
            (),
            ("result == len(s)", "result > 1"),
            {"s": '["b", "a"]'},
        ),
        "budget",
        budget=3,
    )

    assert len(cases) == 60, f"العدّة التعاقدية 60 حالة — وجدنا {len(cases)}"
    return tuple(cases)


CASES: tuple[SynthCase, ...] = _cases()


def _run_case(case: SynthCase) -> SynthReceipt:
    """شغّل حالة واحدة بالحدود المعلنة — بلا أزمنة في المخرج."""
    kwargs: dict[str, int] = {}
    if case.max_nodes is not None:
        kwargs["max_nodes"] = case.max_nodes
    if case.budget is not None:
        kwargs["budget"] = case.budget
    return run(case.source, **kwargs)


def _judge(case: SynthCase, receipt: SynthReceipt) -> tuple[bool, str]:
    """احكم على الحالة — التوقع صادق: الفئة تحكم الشكل كله."""
    if receipt.verdict != case.expect_verdict:
        return False, (f"الحكم '{receipt.verdict}' خالف التوقع '{case.expect_verdict}'")
    if case.expect_verdict == CAT_SYNTH:
        if receipt.winner_expr is None or receipt.winner_source is None:
            return False, "حالة تركيب بلا فائز أو بلا مصدر"
        if receipt.formal.get("verdict") != "accept":
            return False, "الفائز لم يُحكَم من الحاكم الشكلي"
    if case.expect_verdict == CAT_EXHAUST:
        if receipt.winner_expr is not None:
            return False, "برهان غياب بفائز — تناقض"
        if receipt.search.get("budget_hit"):
            return False, "البرهان قطعته الميزانية — ليس برهاناً كاملاً"
        if case.case_id == "S-0042" and "خارج المسبقات" not in receipt.reason_ar:
            return False, "برهان استبعاد المسبقات بلا سببه الصريح"
    return True, ""


def run_synth_lab() -> SynthLabReport:
    """شغّل العدّة كاملة — إيصال حتمي بالبايت، فشل صادق."""
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    by_category: dict[str, dict[str, object]] = {
        cat: {"passed": 0, "rate": 0.0, "total": 0, "verdict_ar": ""} for cat in CATEGORY_ORDER
    }

    for case in CASES:
        receipt = _run_case(case)
        ok, problem = _judge(case, receipt)
        rows.append(
            {
                "case_id": case.case_id,
                "ok": ok,
                "problem_ar": problem,
                "reason_ar": receipt.reason_ar,
                "title_ar": case.title_ar,
                "tried": receipt.tried,
                "verdict": receipt.verdict,
                "winner_expr": receipt.winner_expr,
            }
        )
        stats = by_category[case.category]
        stats["total"] = int(stats["total"]) + 1
        if ok:
            stats["passed"] = int(stats["passed"]) + 1
        else:
            failures.append(f"{case.case_id} ({case.title_ar}): {problem}")

    for cat in CATEGORY_ORDER:
        stats = by_category[cat]
        total = int(stats["total"])
        passed = int(stats["passed"])
        stats["rate"] = round(100.0 * passed / total, 1) if total else 0.0
        stats["verdict_ar"] = (
            "قوة"
            if total and passed == total
            else "مراقبة"
            if total and passed / total >= 0.85
            else "ضعف"
        )

    payload = "\x1f".join(
        f"{r['case_id']}\x1f{r['verdict']}\x1f{r['winner_expr'] or ''}" for r in rows
    )
    chain_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    passed = sum(int(s["passed"]) for s in by_category.values())
    return SynthLabReport(
        total=len(CASES),
        passed=passed,
        failed=len(CASES) - passed,
        by_category=by_category,
        rows=tuple(rows),
        chain_hash=chain_hash,
        ok=passed == len(CASES),
        failures=tuple(failures),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zyko.benchmarks.synthlab",
        description="معمل المُقترِح الحتمي — 60 حالة تقيس البرمجة بلا نموذج",
    )
    parser.add_argument("--run", action="store_true", help="شغّل العدّة كاملة")
    parser.add_argument("--json", default=None, help="اكتب الإيصال في ملف")
    args = parser.parse_args(argv)
    if not args.run:
        parser.error("حدّد --run لتشغيل العدّة")
        return 2
    report = run_synth_lab()
    print(report.table_ar())
    if args.json:
        Path(args.json).write_text(report.to_json() + "\n", encoding="utf-8")
        print(f"الإيصال كُتب: {args.json}")
    for failure in report.failures:
        print(f"فشل: {failure}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
