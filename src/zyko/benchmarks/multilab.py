"""zyko.benchmarks.multilab — معمل الترقيع متعدد الملفات: العمق الوكيلي يقاس لا يُفترض.

بعد الجولة 8 كانت الفجوة الموثقة الأولى «العمق الوكيلي متعدد الملفات —
البنية جاهزة والناقص سياسة التخطيط». الجولة 17 بنت السياسة
(``zyko.coder.multiplan``)، وهذا المعمل هو مقياسها الصادق: تسعة
سيناريوهات على ثلاث فئات، كل واحد شجرة مشروع حقيقية تُبنى على القرص
من محتوى معلن حتمي، ثم يُقاس سلوك المحرك على العقد:

1. **فئة الاستكشاف (discovery)** — هل يرى المسح كل ملفات المرجع ولا
   يغلط في غيرها؟ الأرض المرجعية معلنة عند البذر: ملفات يجب أن تظهر
   وملفات فخاخ (سلاسل وتعليقات تحمل الاسم) يجب ألا تظهر. المقياس:
   تطابق تام صفر توبيخ.
2. **فئة التنفيذ (execution)** — من المسح إلى الخطة إلى الصفقة:
   إعادة تسمية كاملة، ثم **حفظ السلوك** يقاس بذور محسوبة: نواتج
   الدوال تُسجَّل قبل التسمية باسمها القديم وتُعاد بعدها باسمها الجديد
   عبر تحميل وحدات الملفات مباشرة — تطابق النواتج هو العقد.
3. **فئة الصفقة (transaction)** — الفشل جزء من العقد لا خارجه:
   خطوة تنكسر وسط الصفقة فتُرجع ما قبلها، وخطة ناقصة التغطية تُرجع
   كاملة، والإرجاع نفسه يثبت بالبايت (بصمات الملفات بعد الإرجاع ==
   بصماتها قبل الترقيع).

القواعد كما في كل معمل:
- **حتمية بالبايت (P6)** — نفس البذور ⇒ نفس الإيصال بالبايت؛ لا
  أزمنة ولا عشوائية ولا ترتيب قاموس خام.
- **فشل صادق** — أي سيناريو لا يطابق عقده يعود صفًا فاشلًا بمشكلة
  عربية صريحة؛ لا يُخفى ولا يُعتذر عنه.

    from zyko.benchmarks.multilab import run_multilab

    report = run_multilab()
    assert report.all_passed
    print(report.table_ar())
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.coder.multiplan import (
    MultiFilePlan,
    MultiFilePlanError,
    PlanStep,
    apply_plan,
    build_rename_plan,
    find_symbol_references,
)
from zyko.sandbox.contracts import PermissionContract

__all__ = [
    "CATEGORIES",
    "CATEGORY_AR",
    "CATEGORY_DISCOVERY",
    "CATEGORY_EXECUTION",
    "CATEGORY_TRANSACTION",
    "MultiLabReport",
    "MultiLabRow",
    "run_multilab",
]

# ------------------------------------------------------------------ الفئات
CATEGORY_DISCOVERY = "discovery"
CATEGORY_EXECUTION = "execution"
CATEGORY_TRANSACTION = "transaction"

CATEGORIES: tuple[str, ...] = (CATEGORY_DISCOVERY, CATEGORY_EXECUTION, CATEGORY_TRANSACTION)

CATEGORY_AR: dict[str, str] = {
    CATEGORY_DISCOVERY: "استكشاف — المرجع يُرى بالشجرة لا بالنص",
    CATEGORY_EXECUTION: "تنفيذ — من الخطة إلى الصفقة بحفظ السلوك",
    CATEGORY_TRANSACTION: "صفقة — الفشل يُرجع والبايت يشهد",
}


def _sha16(text: str) -> str:
    """بصمة موصرة للنص — للإيصال لا للتحقق الكامل."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _write_tree(root: Path, files: dict[str, str]) -> None:
    """بذر شجرة مشروع من قاموس مسارات posix — حتمي بالترتيب المفرز."""
    for rel in sorted(files):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[rel], encoding="utf-8")


# ------------------------------------------------------------------ البذور
def _seed_discovery_simple() -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    """ML-D1 — ثلاثة ملفات: تعريف، استدعاء مباشر، استيراد من-؛ وفخاخ نصية."""
    files = {
        "calc.py": (
            "def scale(x):\n"
            "    return x * 3\n"
            "\n"
            "\n"
            "def twice(y):\n"
            "    return scale(y) + scale(1)\n"
        ),
        "app.py": "from calc import scale\n\n\ndef run():\n    return scale(5) + twice(2)\n",
        "views.py": "import calc\n\n\ndef render():\n    return calc.scale(9)\n",
        # فخاخ: الاسم في سلسلة وتعليق — ليس مرجعًا معرفيًا
        "strings.py": 'DOC = "scale is documented here"\n# scale comment\n',
        "readme.txt": "scale mentioned in plain text\n",
    }
    expected = ("app.py", "calc.py", "views.py")
    decoys = ("strings.py",)
    return files, "scale", expected, decoys


def _seed_discovery_attributes() -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    """ML-D2 — وصول عبر الوحدة واستيراد من-؛ وملف فخ يرشح رمزًا آخر فلا يظهر."""
    files = {
        "pkg/__init__.py": "",
        "pkg/core.py": (
            "def audit(entries, limit=0):\n"
            "    return len(entries) + limit\n"
        ),
        "pkg/use.py": (
            "from pkg.core import audit\n"
            "\n"
            "\n"
            "def check(items):\n"
            "    return audit(items, limit=2)\n"
        ),
        "pkg/other.py": (
            "from . import core\n"
            "\n"
            "\n"
            "def bad(x):\n"
            "    return core.audit([x])\n"
        ),
        # فخ: يرشح Report وtotal — رمزًا آخر كله فلا يدخل مسح audit
        "pkg/report.py": (
            "class Report:\n"
            "    def __init__(self, total=0):\n"
            "        self.total = total\n"
            "\n"
            "\n"
            "def make():\n"
            "    r = Report(total=1)\n"
            "    return r.total\n"
        ),
    }
    expected = ("pkg/core.py", "pkg/other.py", "pkg/use.py")
    decoys = ("pkg/report.py",)
    return files, "audit", expected, decoys


def _seed_discovery_shadow() -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    """ML-D3 — تعريف واحد ومرجع معرفي داخل نفس الملف فقط؛ والفخ الأسير."""
    files = {
        "solo.py": (
            "def helper(n):\n"
            "    return n + 1\n"
            "\n"
            "\n"
            "def caller(n):\n"
            "    return helper(n) * helper(0)\n"
        ),
        # فخ: معرف بنفس الاسم في سلسلة نصية داخل كود سليم
        "notes.py": 'HINT = "helper does the increment"\n',
    }
    expected = ("solo.py",)
    decoys = ("notes.py",)
    return files, "helper", expected, decoys


def _seed_execution_pkg() -> tuple[dict[str, str], str, str]:
    """ML-E1 — حزمة حقيقية: تعريف + استيراد + استدعاء؛ والسلوك بذور معلنة."""
    files = {
        "pkg/__init__.py": "",
        "pkg/ops.py": (
            "def transform(values):\n"
            '    """يجمع الفروقات المطلقة."""\n'
            "    return sum(abs(a - b) for a, b in zip(values, values[1:]))\n"
        ),
        "pkg/report.py": "from pkg.ops import transform\n\n\ndef summarize(v):\n    return transform(v) + 1\n",
        "app.py": "import pkg.report\n\n\ndef run(v):\n    return pkg.report.summarize(v)\n",
    }
    return files, "transform", "shift"


def _seed_execution_multi() -> tuple[dict[str, str], str, str]:
    """ML-E2 — الاسم يعبر ثلاثة ملفات بثلاثة أنماط: دالة ووسيطة وسمة وحدة."""
    files = {
        "m/__init__.py": "",
        "m/base.py": (
            "def weight(v):\n"
            "    return len(v) * 2\n"
        ),
        "m/mid.py": (
            "from m.base import weight\n"
            "\n"
            "\n"
            "def score(v, mass=None):\n"
            "    w = mass if mass is not None else 1\n"
            "    return weight(v) + w\n"
        ),
        "m/top.py": (
            "import m.base\n"
            "\n"
            "\n"
            "def final(v):\n"
            "    return m.base.weight(v) * 10\n"
        ),
    }
    return files, "weight", "heft"


def _seed_execution_const() -> tuple[dict[str, str], str, str]:
    """ML-E3 — ثابت معرَّف ومستورد ومستخدم — إعادة تسمية فوق الحدود."""
    files = {
        "cfg.py": "LIMIT = 7\n\n\ndef capped(n):\n    return min(n, LIMIT)\n",
        "main.py": "from cfg import LIMIT\n\n\ndef gate(n):\n    return n if n < LIMIT else 0\n",
    }
    return files, "LIMIT", "CEILING"


# ------------------------------------------------------------------ الصف
@dataclass(frozen=True)
class MultiLabRow:
    """صف سيناريو واحد: عقده وقراره ودليله — بلا أزمنة."""

    scenario_id: str
    category: str
    passed: bool
    detail_ar: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "detail_ar": self.detail_ar,
            "evidence": self.evidence,
            "passed": bool(self.passed),
            "scenario_id": self.scenario_id,
        }


@dataclass(frozen=True)
class MultiLabReport:
    """تقرير المعمل: صفوف مرتبة بالمعرف، عدّ الفئات، وبصمة السلسلة."""

    rows: tuple[MultiLabRow, ...]
    receipt_sha256: str = ""

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.rows)

    def category_counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for cat in CATEGORIES:
            cat_rows = [r for r in self.rows if r.category == cat]
            out[cat] = {
                "total": len(cat_rows),
                "passed": sum(1 for r in cat_rows if r.passed),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": bool(self.all_passed),
            "categories": self.category_counts(),
            "rows": [r.to_dict() for r in self.rows],
            "total": len(self.rows),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=1)

    def table_ar(self) -> str:
        """جدول عربي للفئات الثلاث — كل صف عقده وقراره."""
        lines = [
            "معمل الترقيع متعدد الملفات — العقد يقاس لا يُفترض:",
            "",
        ]
        for cat in CATEGORIES:
            counts = self.category_counts()[cat]
            lines.append(
                f"[{CATEGORY_AR[cat]}] {counts['passed']}/{counts['total']}"
            )
            for row in self.rows:
                if row.category == cat:
                    mark = "أخضر" if row.passed else "أحمر"
                    lines.append(f"  {row.scenario_id} — {mark} — {row.detail_ar}")
        lines.append("")
        lines.append(
            f"المجموع: {sum(1 for r in self.rows if r.passed)}/{len(self.rows)} — "
            f"بصمة السلسلة: {self.receipt_sha256[:16]}…"
        )
        return "\n".join(lines)


# ------------------------------------------------------------- السيناريوهات
def _run_discovery_simple() -> MultiLabRow:
    files, sym, expected, decoys = _seed_discovery_simple()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        scan = find_symbol_references(root, sym)
        got = scan.touched_paths
        ok = got == expected
        detail = (
            f"المسح رأى {len(got)}/{len(expected)} ملفات المرجع"
            if ok
            else f"التطابق فشل — ظهر {got} والمطلوب {expected}"
        )
        return MultiLabRow(
            scenario_id="ML-D1",
            category=CATEGORY_DISCOVERY,
            passed=ok,
            detail_ar=detail,
            evidence={
                "decoys_excluded": sorted(set(decoys) - set(got)),
                "expected": list(expected),
                "got": list(got),
                "references": len(scan.references),
            },
        )


def _run_discovery_attributes() -> MultiLabRow:
    files, sym, expected, decoys = _seed_discovery_attributes()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        scan = find_symbol_references(root, sym)
        got = scan.touched_paths
        ok = got == expected
        detail = (
            f"الوصول عبر الوحدة والوسيطة المسماة رُئيا: {len(got)} ملفات"
            if ok
            else f"التطابق فشل — ظهر {got} والمطلوب {expected}"
        )
        return MultiLabRow(
            scenario_id="ML-D2",
            category=CATEGORY_DISCOVERY,
            passed=ok,
            detail_ar=detail,
            evidence={
                "decoys_excluded": sorted(set(decoys) - set(got)),
                "expected": list(expected),
                "got": list(got),
                "import_refs": len(scan.import_refs),
                "references": len(scan.references),
            },
        )


def _run_discovery_shadow() -> MultiLabRow:
    files, sym, expected, decoys = _seed_discovery_shadow()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        scan = find_symbol_references(root, sym)
        got = scan.touched_paths
        ok = got == expected and len(scan.definitions) == 1
        detail = (
            "التعريف وحيد ومراجعه داخل ملف واحد — الفخ النصي استُبعد"
            if ok
            else f"التطابق فشل — ظهر {got} والمطلوب {expected}"
        )
        return MultiLabRow(
            scenario_id="ML-D3",
            category=CATEGORY_DISCOVERY,
            passed=ok,
            detail_ar=detail,
            evidence={
                "decoys_excluded": sorted(set(decoys) - set(got)),
                "expected": list(expected),
                "got": list(got),
                "single_definition": len(scan.definitions) == 1,
            },
        )


def _import_outputs(root: Path, calls: list[tuple[str, str, list[list[Any]]]]) -> list[int]:
    """بذور السلوك: حمّل وحدات المشروع من جذره ودعو الدوال على مدخلات معلنة.

    التحميل عبر ``importlib`` مع جذر المشروع في ``sys.path`` مؤقتًا
    وبغسل ``sys.modules`` بعده — فلا تلويث بين السيناريوهات ولا تسرب.
    الاتفاق: كل مدخل في ``arg_list`` وسيط واحد كامل (قائمة أو عدد) —
    تُدعى الدالة عليه دعوة واحدة، فلا تفكك قوائم مدخلات بالخطأ.
    """
    golden: list[int] = []
    sys.path.insert(0, str(root))
    touched: list[str] = []
    try:
        for rel, fn, arg_list in sorted(calls):
            path = root / rel
            if not path.is_file():
                continue
            modname = rel[:-3].replace("/", ".")
            try:
                module = importlib.import_module(modname)
                touched.append(modname)
                func = getattr(module, fn)
                for args in arg_list:
                    golden.append(int(func(args)))
            except (ImportError, AttributeError, SyntaxError, TypeError, OSError, ValueError):
                return []
    finally:
        if str(root) in sys.path:
            sys.path.remove(str(root))
        for modname in touched:
            sys.modules.pop(modname, None)
        # وحدات الحزم الفرعية تُغسل أيضًا (pkg وm أنفسهما)
        for stale in [
            k
            for k in list(sys.modules)
            if k.split(".")[0] in {"pkg", "m", "app", "app2", "cfg", "main", "calc"}
        ]:
            sys.modules.pop(stale, None)
    return golden


# المدخلات المعلنة لكل سيناريو تنفيذ: (الملف، الدالة، المدخلات) —
# الدالة المُعاد تسميتها تُستدعى باسمها القديم قبل وبالجديد بعد
_EXEC_CALLS: dict[str, list[tuple[str, str, list[list[Any]]]]] = {
    "ML-E1": [
        ("pkg/ops.py", "__SYMBOL__", [[1, 5, 2], [7]]),
        ("pkg/report.py", "summarize", [[1, 5, 2]]),
        ("app.py", "run", [[2, 9, 4]]),
    ],
    "ML-E2": [
        ("m/base.py", "__SYMBOL__", [[1, 2, 3], []]),
        ("m/mid.py", "score", [[1, 2, 3]]),
        ("m/top.py", "final", [[4, 5]]),
    ],
    "ML-E3": [
        ("cfg.py", "capped", [3, 9]),
        ("main.py", "gate", [5, 8]),
    ],
}


def _run_execution(seed_fn, scenario_id: str) -> MultiLabRow:
    files, sym, new = seed_fn()
    golden_calls = [
        (rel, sym if fn == "__SYMBOL__" else fn, args)
        for rel, fn, args in _EXEC_CALLS[scenario_id]
    ]
    post_calls = [
        (rel, new if fn == "__SYMBOL__" else fn, args)
        for rel, fn, args in _EXEC_CALLS[scenario_id]
    ]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        golden = _import_outputs(root, golden_calls)
        if not golden:
            return MultiLabRow(
                scenario_id=scenario_id,
                category=CATEGORY_EXECUTION,
                passed=False,
                detail_ar="البذور القبلية لم تُحسب — علة بذر رفض قبل أي ترقيع",
                evidence={},
            )
        contract = PermissionContract.for_roots(root, allow_patch=True)
        try:
            plan, scan = build_rename_plan(root, contract, symbol=sym, new_name=new)
        except MultiFilePlanError as exc:
            return MultiLabRow(
                scenario_id=scenario_id,
                category=CATEGORY_EXECUTION,
                passed=False,
                detail_ar=f"المخطِّط رفض مشروعًا سليمًا — {exc.problems[0][:60]}",
                evidence={"problems": exc.problems[:3]},
            )
        receipt = apply_plan(contract, plan, root=root)
        behavior = _import_outputs(root, post_calls)
        ok = (
            receipt.ok
            and receipt.applied
            and not receipt.rolled_back
            and receipt.coverage_ok
            and bool(behavior)
            and behavior == golden
            and len(receipt.steps_results) == len(scan.touched_paths)
        )
        detail = (
            f"إعادة التسمية عبر {receipt.files_touched} ملفات والسلوك محفوظ بالبذور"
            if ok
            else (
                f"الصفقة فشلت — {receipt.reason_ar}"
                if not receipt.ok
                else f"السلوك انكسر — قبل {golden[:4]} بعد {behavior[:4]}"
            )
        )
        return MultiLabRow(
            scenario_id=scenario_id,
            category=CATEGORY_EXECUTION,
            passed=ok,
            detail_ar=detail,
            evidence={
                "coverage": receipt.coverage_detail,
                "files": receipt.files_touched,
                "golden": golden[:6],
                "post": behavior[:6],
            },
        )


def _seed_transaction_mid_fail() -> tuple[MultiFilePlan, dict[str, str], str]:
    """ML-T1 — خطوة وسطية تنكسر (old_text غير موجود) فتُرجع سابقتها."""
    files = {
        "a.py": "def keeper():\n    return 1\n",
        "b.py": "def breaker():\n    return 2\n",
    }
    plan = MultiFilePlan(
        goal_ar="صفقة بخطوة تنكسر وسطًا — الإرجاع جزء من العقد",
        kind="custom",
        steps=(
            PlanStep(
                path="a.py",
                kind="write",
                content="def keeper():\n    return 11\n",
                purpose_ar="خطوة سليمة تُطبق أولًا",
            ),
            PlanStep(
                path="b.py",
                kind="replace",
                old_text="النص غير موجود أصلًا",
                new_text="x",
                purpose_ar="خطوة تنكسر — تطابق صفري رفض",
            ),
        ),
    )
    return plan, files, "a.py"


def _run_transaction_mid_fail() -> MultiLabRow:
    plan, files, applied_rel = _seed_transaction_mid_fail()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        before_sha = _sha16(files[applied_rel])
        contract = PermissionContract.for_roots(root, allow_patch=True)
        receipt = apply_plan(contract, plan, root=root)
        after_content = (root / applied_rel).read_text(encoding="utf-8")
        ok = (
            not receipt.ok
            and receipt.rolled_back
            and applied_rel in receipt.restored_paths
            and "return 1" in after_content
            and "return 11" not in after_content
            and not receipt.restore_failures
        )
        return MultiLabRow(
            scenario_id="ML-T1",
            category=CATEGORY_TRANSACTION,
            passed=ok,
            detail_ar=(
                f"الخطوة الكاسرة أوقفت الصفقة وأُرجع {len(receipt.restored_paths)} ملف"
                if ok
                else f"الإرجاع فشل — {receipt.reason_ar}"
            ),
            evidence={
                "before_sha": before_sha,
                "rolled_back": receipt.rolled_back,
                "restored": list(receipt.restored_paths),
            },
        )


def _seed_transaction_coverage() -> tuple[dict[str, str], str, str]:
    """ML-T2 — خطة تعيد التسمية وتترك ملفًا مرجعيًا خارجها فتُرجع كاملة."""
    files = {
        "core.py": "def mover(n):\n    return n + 1\n",
        "side.py": "from core import mover\n\n\ndef use(n):\n    return mover(n) * 2\n",
    }
    return files, "mover", "shifted"


def _run_transaction_coverage() -> MultiLabRow:
    files, sym, new = _seed_transaction_coverage()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        # خطة يدوية ناقصة: تلمس التعريف وتترك side.py المرجعي
        plan = MultiFilePlan(
            goal_ar="خطة ناقصة التغطية — تُرفض وقت التنفيذ لا وقت الادعاء",
            kind="rename",
            symbol=sym,
            new_name=new,
            steps=(
                PlanStep(
                    path="core.py",
                    kind="write",
                    content="def shifted(n):\n    return n + 1\n",
                    purpose_ar="تعريف بلا مراجع — خطة كاذبة مقصودة",
                ),
            ),
        )
        contract = PermissionContract.for_roots(root, allow_patch=True)
        receipt = apply_plan(contract, plan, root=root)
        ok = (
            not receipt.ok
            and receipt.rolled_back
            and "core.py" in receipt.restored_paths
            and f"def {sym}" in (root / "core.py").read_text(encoding="utf-8")
            and receipt.coverage_detail.get("old_left", 0) > 0
        )
        return MultiLabRow(
            scenario_id="ML-T2",
            category=CATEGORY_TRANSACTION,
            passed=ok,
            detail_ar=(
                "الخطة التي تركت مرجعًا رُفضت وأُرجعت بالبايت"
                if ok
                else f"التغطية لم تُمسك — {receipt.reason_ar}"
            ),
            evidence={
                "coverage": receipt.coverage_detail,
                "rolled_back": receipt.rolled_back,
            },
        )


def _run_transaction_restore() -> MultiLabRow:
    """ML-T3 — وفاء الإرجاع بالبايت: بصمات الملفات بعد الإرجاع == قبل الترقيع."""
    plan, files, _ = _seed_transaction_mid_fail()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_tree(root, files)
        before = {rel: _sha16(content) for rel, content in sorted(files.items())}
        contract = PermissionContract.for_roots(root, allow_patch=True)
        receipt = apply_plan(contract, plan, root=root)
        after = {
            rel: _sha16((root / rel).read_text(encoding="utf-8"))
            for rel in sorted(files)
        }
        ok = (
            receipt.rolled_back
            and before == after
            and not receipt.restore_failures
        )
        return MultiLabRow(
            scenario_id="ML-T3",
            category=CATEGORY_TRANSACTION,
            passed=ok,
            detail_ar=(
                "بصمات الملفات بعد الإرجاع تطابق قبل الترقيع بالبايت"
                if ok
                else f"الإرجاع غير وفاء — {receipt.restore_failures}"
            ),
            evidence={"after": after, "before": before},
        )


# ------------------------------------------------------------------ المعمل
def run_multilab() -> MultiLabReport:
    """شغّل السيناريوهات التسعة بالترتيب المفرز وابنِ التقرير الموقَّع."""
    rows = (
        _run_discovery_simple(),
        _run_discovery_attributes(),
        _run_discovery_shadow(),
        _run_execution(_seed_execution_pkg, "ML-E1"),
        _run_execution(_seed_execution_multi, "ML-E2"),
        _run_execution(_seed_execution_const, "ML-E3"),
        _run_transaction_mid_fail(),
        _run_transaction_coverage(),
        _run_transaction_restore(),
    )
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
    return MultiLabReport(rows=rows, receipt_sha256=digest.hexdigest())


if __name__ == "__main__":
    report = run_multilab()
    print(report.table_ar())
    raise SystemExit(0 if report.all_passed else 1)
