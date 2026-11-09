"""zyko.workspace.gate — بوابة قبول المرحلة 5: ست بوابات كمية أولًا بأول.

- W1 التكامل  : كل مرساة (مجلد قائم مُركَّب في الذاكرة) تُكمل (مسح ←
  مراجعة ← إصلاح) بلا فشل، وبإصلاحات فعلية
- W2 الحتمية  : تشغيلان على نسختين متطابقتين ⇒ حمولتان متطابقتان بايت-ببايت
- W3 الاعتدال : تشغيل المحرك على ناتجه النهائي ⇒ صفر تغيير
- W4 التحسن   : لا ملف يتراجع (score_after ≥ score_before) وإصلاحات > 0
- W5 المتانة  : مدخلات عدائية (12) ⇒ فشل مهيكل عربي، لا استثناءات
- W6 الأداء   : التشغيل الكامل لكل مرساة أسرع من الحد المعلن
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.workspace.engine import (
    STAGE_WORKSPACE,
    STAGES,
    WRITE_COPY,
    WRITE_INPLACE,
    WRITE_NONE,
    WorkspaceEngine,
    WorkspaceResult,
)

# مراسٍ البوابة: (الاسم، {مسار نسبي: نص المصدر}) — ثلاثة أشجار واقعية:
# مشروع صغير مسطح، حزمة بمجلدات فرعية، وشجرة مختلطة بملفات فاسدة عمدًا
# (صياغة مكسورة + ترميز ليس UTF-8) لتوثيق سلوك التخطي الآمن.
_CLI_MAIN = '''"""أداة سطر أوامر صغيرة — مشروع قائم عمدًا فيه ما يُصلَح."""
import os


def flip(flag):
    return flag == None


retry = lambda n: n - 1


def guarded(block):
    try:
        block()
    except:
        raise ValueError("فشل")


def load(path):
    f = open(path)
    data = f.read()
    f.close()
    return data
'''

_CLI_STORE = '''import hashlib


def token(secret):
    """بصمة سر — خوارزمية قديمة عمدًا."""
    return hashlib.md5(secret).hexdigest()
'''

_PKG_CORE = """from json import dumps


def render(row):
    return dumps(row, ensure_ascii=False)
"""

_PKG_UTIL = """import sys


def pick(items, i):
    if items is None:
        return None
    return items[i] if i != None else None
"""

_MIX_BROKEN = """def half(:
    return 1
"""

_MIX_BADENC = "def اسم(نص):\n    return نص.upper()\n".encode("utf-16")

_MIX_CLEAN = '''"""ملف نظيف تمامًا — يجب أن يبقى كما هو بلا أي تغيير."""


def add(a: int, b: int) -> int:
    """يجمع عددين."""
    return a + b
'''

ANCHORS: tuple[tuple[str, dict[str, "str | bytes"]], ...] = (
    ("small-cli", {"cli_main.py": _CLI_MAIN, "cli_store.py": _CLI_STORE}),
    (
        "pkg-lib",
        {
            "pkg/__init__.py": _PKG_CORE,
            "pkg/core.py": _PKG_CORE,
            "pkg/util.py": _PKG_UTIL,
        },
    ),
    (
        "mixed-tree",
        {
            "app.py": _CLI_STORE,
            "clean_mod.py": _MIX_CLEAN,
            "broken.py": _MIX_BROKEN,
            "legacy_utf16.py": _MIX_BADENC,
            "notes.txt": "ملف نصي ليس بايثون — يجب ألا يُلمس",
        },
    ),
)

# مدخلات W5 العدائية — كلها يجب أن تعيد فشلًا مهيكلًا عربيًا (خروج 2).
# كل مدخل: (الوسم، معاملات run) — مفاتيح خاصة: occupied_file وoccupied_dir
# وsrc_is_file تُبنى داخل مجلد البوابة قبل الاستدعاء.
_HOSTILE_LABELS: tuple[str, ...] = (
    "مجلد غير موجود",
    "ملف بدل مجلد",
    "مسار معدوم النوع",
    "مسار رقمي",
    "مسار بايتات",
    "جولات سالبة",
    "جولات نصية",
    "جولات منطقية",
    "مخرج غير فارغ",
    "موضعي بلا تأكيد",
    "نسخ وموضعي معًا",
    "نمط كتابة مجهول",
)
HOSTILE_TOTAL = len(_HOSTILE_LABELS)


@dataclass
class GateRow:
    """نتيجة مرساة واحدة داخل البوابة (أو سطر مشكلة متانة بوصف فارغ)."""

    name: str
    description: str
    completed: bool = False
    deterministic: bool = False
    idempotent: bool = False
    improved: bool = False
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.completed and self.deterministic and self.idempotent and self.improved


@dataclass
class Phase5GateResult:
    """نتيجة البوابة كاملة: صفوف المراسي + المتانة + الزمن."""

    rows: list[GateRow] = field(default_factory=list)
    robustness_passed: int = 0
    robustness_total: int = HOSTILE_TOTAL
    max_seconds: float = 5.0

    @property
    def ok(self) -> bool:
        rows_ok = all(r.passed for r in self.rows) and bool(self.rows)
        perf_ok = all(r.seconds < self.max_seconds for r in self.rows)
        return rows_ok and self.robustness_passed == self.robustness_total and perf_ok

    def table_ar(self) -> str:
        lines = [
            "بوابة المرحلة 5 — المحرك على أرض الواقع (مسح ← مراجعة ← إصلاح لمجلد قائم)",
            f"{'المرساة':<14}{'اكتمال':<9}{'حتمية':<8}{'اعتدال':<8}{'تحسن':<7}{'ثوانٍ':>6}",
            "-" * 56,
        ]
        for r in self.rows:
            lines.append(
                f"{r.name:<14}"
                f"{'نعم' if r.completed else 'لا':<9}"
                f"{'نعم' if r.deterministic else 'لا':<8}"
                f"{'نعم' if r.idempotent else 'لا':<8}"
                f"{'نعم' if r.improved else 'لا':<7}"
                f"{r.seconds:>6.2f}"
            )
            for p in r.problems:
                lines.append(f"  ↳ {p}")
        lines.append("-" * 56)
        lines.append(
            f"المتانة: {self.robustness_passed}/{self.robustness_total} مدخلًا عدائيًا فشل فشلًا مهيكلًا آمنًا"
        )
        lines.append("النتيجة: البوابة ناجحة ✅" if self.ok else "النتيجة: البوابة فاشلة ❌")
        return "\n".join(lines)


def _build_tree(root: Path, files: dict[str, "str | bytes"]) -> None:
    """يركّب شجرة مرساة في مجلد — بترتيب حتمي؛ bytes تُكتب كما هي."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8", newline="\n")


def _check_idempotence(first: WorkspaceResult, tmp: Path, label: str) -> list[str]:
    """W3: تشغيل المحرك على ناتجه النهائي ⇒ صفر تغيير إطلاقًا."""
    problems: list[str] = []
    out = tmp / f"{label}-idem"
    _build_tree(out, first.final_sources)
    engine = WorkspaceEngine()
    again = engine.run(out, rounds=1)
    if not again.ok:
        problems.append(f"إعادة التشغيل على الناتج فشلت: {again.error_ar}")
    elif again.changed_files != 0:
        problems.append(f"الاعتدال مكسور: المحرك غيّر {again.changed_files} من ملفات ناتجه هو")
    return problems


def _run_anchor(
    engine: WorkspaceEngine, label: str, files: dict[str, "str | bytes"], tmp: Path
) -> GateRow:
    row = GateRow(name=label, description="، ".join(sorted(files)))
    started = time.perf_counter()
    src1, src2 = tmp / f"{label}-1", tmp / f"{label}-2"
    _build_tree(src1, files)
    _build_tree(src2, files)
    first = engine.run(src1, rounds=1)
    row.seconds = time.perf_counter() - started

    # W1 التكامل
    if not first.ok:
        row.problems.append(f"فشل في {first.failed_stage}: {first.error_ar}")
        return row
    if first.reviewed == 0:
        row.problems.append("لم تُراجَع أي ملفات بايثون قابلة للتحليل")
        return row
    row.completed = True

    # W4 التحسن: لا تراجع في أي ملف + إصلاحات فعلية
    regressions = [
        f["path"]
        for f in first.per_file
        if f["status"] != "skipped" and f["score_after"] < f["score_before"]
    ]
    if regressions:
        row.problems.append(f"ملفات تراجعت درجتها: {', '.join(regressions)}")
    if first.fixed_total == 0:
        row.problems.append("لا إصلاحات — المراسي يجب أن تُظهر قيمة المحرك")
    row.improved = not regressions and first.fixed_total > 0

    # W3 الاعتدال
    idem = _check_idempotence(first, tmp, label)
    row.problems.extend(idem)
    row.idempotent = not idem

    # W2 الحتمية: نسخة ثانية متطابقة ⇒ نفس البايتات (بعد توحيد حقل المسار —
    # فالمجلدان مختلفان اسمًا بحكم التركيب، وكل ما سواه يجب أن يتطابق)
    second = engine.run(src2, rounds=1)

    def _normalized(res: WorkspaceResult) -> str:
        d = res.to_dict()
        d["src"] = "<anchor>"
        return json.dumps(d, ensure_ascii=False, indent=2)

    row.deterministic = _normalized(first) == _normalized(second)
    if not row.deterministic:
        row.problems.append("تشغيلان على نسختين متطابقتين أعطيا حمولتين مختلفتين")
    return row


def _check_robustness(engine: WorkspaceEngine, tmp: Path) -> tuple[int, int, list[str]]:
    """W5: كل مدخل عدائي ⇒ فشل مهيكل عربي (خروج 2) بلا أي استثناء."""
    passed = 0
    problems: list[str] = []
    good = tmp / "good-proj"
    _build_tree(good, {"mod.py": _CLI_STORE})

    occupied = tmp / "occupied-out"
    occupied.mkdir(parents=True, exist_ok=True)
    (occupied / "يوجد-ملف.txt").write_text("لا تمسّني", encoding="utf-8")

    plain_file = tmp / "plain.txt"
    plain_file.write_text("ملف لا مجلد", encoding="utf-8")

    cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("مجلد غير موجود", {"src": tmp / "لا-يوجد"}),
        ("ملف بدل مجلد", {"src": plain_file}),
        ("مسار معدوم النوع", {"src": None}),
        ("مسار رقمي", {"src": 42}),
        ("مسار بايتات", {"src": b"/tmp/bytes"}),
        ("جولات سالبة", {"src": good, "rounds": -1}),
        ("جولات نصية", {"src": good, "rounds": "كثيرة"}),
        ("جولات منطقية", {"src": good, "rounds": True}),
        ("مخرج غير فارغ", {"src": good, "write": WRITE_COPY, "out_dir": occupied}),
        ("موضعي بلا تأكيد", {"src": good, "write": WRITE_INPLACE}),
        (
            "نسخ وموضعي معًا",
            {
                "src": good,
                "write": WRITE_INPLACE,
                "out_dir": tmp / "conflict",
                "confirm_inplace": True,
            },
        ),
        ("نمط كتابة مجهول", {"src": good, "write": "حذف"}),
    )
    total = len(cases)
    for label, kwargs in cases:
        try:
            result = engine.run(
                kwargs.get("src"),
                rounds=kwargs.get("rounds", 1),  # type: ignore[arg-type]
                write=kwargs.get("write", WRITE_NONE),  # type: ignore[arg-type]
                out_dir=kwargs.get("out_dir"),
                confirm_inplace=bool(kwargs.get("confirm_inplace", False)),
            )
        except Exception as exc:  # noqa: BLE001 — البوابة تُحصي الانهيار كمدخل فاشل
            problems.append(f"«{label}» رفع استثناء {type(exc).__name__} — يجب فشل مهيكل")
            continue
        structured = (
            not result.ok
            and result.exit_code == 2
            and result.failed_stage in (*STAGES, STAGE_WORKSPACE)
            and bool(result.error_ar)
        )
        if structured:
            passed += 1
        else:
            problems.append(
                f"«{label}» لم يُنتج فشلًا مهيكلاً (ok={result.ok}, exit={result.exit_code})"
            )
    return passed, total, problems


def run_phase5_gate(
    anchors: tuple[tuple[str, dict[str, "str | bytes"]], ...] | None = None,
    *,
    max_seconds: float = 5.0,
    tmp_root: str | Path | None = None,
) -> Phase5GateResult:
    """تشغيل البوابة كاملة — حتمية في الحكم، بلا شبكة وبلا نموذج."""
    cases = anchors or ANCHORS
    engine = WorkspaceEngine()
    result = Phase5GateResult(max_seconds=max_seconds)
    with tempfile.TemporaryDirectory(prefix="zyko-p5-gate-", dir=tmp_root) as td:
        tmp = Path(td)
        for label, files in cases:
            result.rows.append(_run_anchor(engine, label, files, tmp))
        result.robustness_passed, result.robustness_total, rb = _check_robustness(engine, tmp)
    # مشاكل المتانة تُعرض في جدول البوابة دون أن تفسد صفوف المراسي —
    # فشلها محسوب أصلًا في robustness_passed مقابل robustness_total.
    for p in rb:
        result.rows.append(GateRow(name="متانة", description="", problems=[p]))
    return result


__all__ = [
    "ANCHORS",
    "GateRow",
    "HOSTILE_TOTAL",
    "Phase5GateResult",
    "run_phase5_gate",
]
