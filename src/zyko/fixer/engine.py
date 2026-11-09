"""zyko.fixer.engine — محرك الإصلاح: مصدر ⇒ نتيجة موقعة بلا أي انهيار.

العقد المضمون تعاقديًا (نفس روح متانة المراجع في المرحلة 2):
  - مصدر غير قابل للتحليل ⇒ نتيجة مهيكلة (parse_error) بلا أي قطعة
  - كل إصلاح يُتحقق منه: النص بعد القطع يُعاد تحليله بـ ast، وإلا سقطت
    المجموعة كاملةً وعادت ملاحظاتها بحالة «مفتوح» بتفسير عربي
  - سلاسل الإصلاح تُدار بجولات متتالية (حتى 3): إصلاح اللامدا يولّد دالة
    بلا docstring فتُصلَح في الجولة التالية — بلا تدخل ولا مفاجآت
  - المخرجات حتمية بايتيًا (include_timing=False افتراضيًا) — نفس المصدر
    ⇒ نفس البايتات، ونفس المصدر مرة ثانية ⇒ لا تغيير إطلاقًا (الاعتدال)
المحرك لا يلمس الشبكة أبدًا ولا يستورد خارج المكتبة القياسية وحزمة zyko.
"""

from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.fixer.edits import Edit, SourceText, apply_edits, parses
from zyko.fixer.fixes import (
    ACTION_AR,
    AUTO_FIXABLE,
    FIX_PLANNERS,
    FixContext,
    manual_reason_ar,
)
from zyko.reviewer.engine import (
    MAX_SOURCE_BYTES,
    SKIP_PARTS,
    ReviewEngine,
    ReviewResult,
    verdict_for_score,
)

# مخطط الحمولة JSON — يتغير فقط بمراجعة مقصودة مع توثيق في CHANGELOG.
SCHEMA = "zyko.fix/1"

# أقصى عدد جولات إصلاح متتالية (سلاسل: 209⇒204 تكفي جولة ثانية، والثالثة أمان).
MAX_PASSES = 3

STATUS_FIXED = "fixed"
STATUS_MANUAL = "manual"
STATUS_OPEN = "open"

STATUS_AR: dict[str, str] = {
    STATUS_FIXED: "أُصلح آليًا",
    STATUS_MANUAL: "يدوي",
    STATUS_OPEN: "يبقى مفتوحًا",
}

_OPEN_PARTIAL_AR = "أُطبق إصلاح جزئي على هذه القاعدة وبقيت حالات بلا مسار آمن — عالجها يدويًا"
_OPEN_NOEDIT_AR = "لا مسار إصلاح آمن لهذه الحالة بعينها — عالجها يدويًا وفق الإصلاح المقترح"
_OPEN_VERIFY_AR = "سقط الإصلاح لفشل التحقق من سلامة الصياغة بعده — لم يُمسّ النص"


@dataclass
class FixOutcome:
    """مصير ملاحظة واحدة: حالة + وصف عربي للإجراء أو سبب البقاء."""

    rule_id: str
    severity: str
    category: str
    line: int
    col: int
    message_ar: str
    suggestion_ar: str
    status: str
    action_ar: str

    @property
    def status_ar(self) -> str:
        return STATUS_AR[self.status]

    def to_dict(self) -> dict[str, Any]:
        from zyko.reviewer.rules import CATEGORY_AR, SEVERITY_AR

        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "severity_ar": SEVERITY_AR[self.severity],
            "category": self.category,
            "category_ar": CATEGORY_AR[self.category],
            "line": self.line,
            "col": self.col + 1,
            "message_ar": self.message_ar,
            "suggestion_ar": self.suggestion_ar,
            "status": self.status,
            "status_ar": self.status_ar,
            "action_ar": self.action_ar,
        }


@dataclass
class FixResult:
    """نتيجة إصلاح ملف واحد: النص الجديد + مصير كل ملاحظة + الدرجات."""

    path: str
    changed: bool
    fixed_source: str
    score_before: int
    score_after: int
    verdict_before_ar: str
    verdict_after_ar: str
    counts_before: dict[str, int] = field(default_factory=dict)
    counts_after: dict[str, int] = field(default_factory=dict)
    outcomes: list[FixOutcome] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    parse_error: str | None = None
    source_sha256: str = ""
    fixed_sha256: str = ""
    seconds: float = 0.0

    @property
    def fixed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == STATUS_FIXED)

    @property
    def manual_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == STATUS_MANUAL)

    @property
    def open_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == STATUS_OPEN)

    @property
    def fixable_remaining(self) -> int:
        """كم ملاحظة قواعد آلية في المصدر الذي جاءت منه هذه النتيجة؟
        (الثابتة والمفتوحة معًا — إذ كلاهما يعني «كان في النص ما يُصلَح»).
        أمر check في CLI يقيس بها: صفر ⇒ النص الحالي بلا ما يُصلَح آليًا."""
        from zyko.fixer.fixes import AUTO_FIXABLE as _AF

        return sum(1 for o in self.outcomes if o.rule_id in _AF)

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "path": self.path,
            "changed": self.changed,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "verdict_before_ar": self.verdict_before_ar,
            "verdict_after_ar": self.verdict_after_ar,
            "counts_before": self.counts_before,
            "counts_after": self.counts_after,
            "fixed_count": self.fixed_count,
            "manual_count": self.manual_count,
            "open_count": self.open_count,
            "edits": [e.to_dict() for e in self.edits],
            "outcomes": [o.to_dict() for o in self.outcomes],
            "fixed_source": self.fixed_source,
            "source_sha256": self.source_sha256,
            "fixed_sha256": self.fixed_sha256,
        }
        if self.parse_error is not None:
            payload["parse_error_ar"] = self.parse_error
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


class FixerEngine:
    """محرك الإصلاح الحتمي: 12 مسارًا آمنًا + تحقق ast + اعتدال مضمون."""

    def __init__(
        self,
        reviewer: ReviewEngine | None = None,
        *,
        rules: tuple[str, ...] | None = None,
        planners: dict[str, Any] | None = None,
    ) -> None:
        """rules تقيّد القواعد الآلية الفعّالة؛ planners تتيح حقن مخططات للاختبار."""
        self.reviewer = reviewer or ReviewEngine()
        active = set(rules) if rules is not None else set(AUTO_FIXABLE)
        self.active_rules: tuple[str, ...] = tuple(r for r in AUTO_FIXABLE if r in active)
        self.planners = dict(FIX_PLANNERS)
        if planners:
            self.planners.update(planners)

    # ------------------------------------------------------------- المصدر
    def fix_source(self, source: str, filename: str = "<text>") -> FixResult:
        """نقطة الدخول الحتمية: مصدر نصي ⇒ نتيجة إصلاح موقعة."""
        started = time.perf_counter()
        sha = hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()[:16]
        base = self.reviewer.review_source(source, filename)
        if base.parse_error is not None:
            return FixResult(
                path=filename,
                changed=False,
                fixed_source=source,
                score_before=0,
                score_after=0,
                verdict_before_ar=base.verdict_ar,
                verdict_after_ar=base.verdict_ar,
                counts_before={s: 0 for s in base.counts},
                counts_after={s: 0 for s in base.counts},
                parse_error=base.parse_error,
                source_sha256=sha,
                fixed_sha256=sha,
                seconds=time.perf_counter() - started,
            )
        current = source
        applied_all: list[Edit] = []
        for _ in range(MAX_PASSES):
            tree = ast.parse(current)
            ctx = FixContext(tree=tree, src=SourceText(current), path=filename)
            snapshot = self.reviewer.review_source(current, filename)
            fixable_ids = {f.rule_id for f in snapshot.findings if f.rule_id in self.active_rules}
            if not fixable_ids:
                break
            edits: list[Edit] = []
            for rid in self.active_rules:
                if rid in fixable_ids and rid in self.planners:
                    try:
                        edits.extend(self.planners[rid](ctx))
                    except Exception:  # noqa: BLE001 — عطب مخطط يُسقط إصلاحه ولا يُسقط المحرك
                        continue  # nosec B112 — التقوية المقصودة: مخطط فاسد يُهمل بأمان
            if not edits:
                break
            candidate, applied, _skipped = apply_edits(current, edits)
            if candidate == current:
                break
            if parses(candidate):
                current = candidate
                applied_all.extend(applied)
                continue
            # التحقق فشل دفعةً واحدة ⇒ نطبق مجموعات القواعد واحدة واحدة بالترتيب
            progressed = False
            for rid in self.active_rules:
                group = [e for e in edits if e.rule_id == rid]
                if not group:
                    continue
                cand_group, applied_group, _ = apply_edits(current, group)
                if cand_group != current and parses(cand_group):
                    current = cand_group
                    applied_all.extend(applied_group)
                    progressed = True
            if not progressed:
                break
        after = self.reviewer.review_source(current, filename)
        resolved: dict[str, bool] = {}
        for rid in self.active_rules:
            resolved[rid] = not any(f.rule_id == rid for f in after.findings)
        outcomes: list[FixOutcome] = []
        for f in base.findings:
            if f.rule_id in self.active_rules:
                if resolved.get(f.rule_id):
                    status, action = STATUS_FIXED, ACTION_AR.get(f.rule_id, "أُصلح آليًا")
                elif any(e.rule_id == f.rule_id for e in applied_all):
                    status, action = STATUS_OPEN, _OPEN_PARTIAL_AR
                else:
                    status, action = STATUS_OPEN, _OPEN_NOEDIT_AR
            else:
                status, action = STATUS_MANUAL, manual_reason_ar(f.rule_id)
            outcomes.append(
                FixOutcome(
                    rule_id=f.rule_id,
                    severity=f.severity,
                    category=f.category,
                    line=f.line,
                    col=f.col,
                    message_ar=f.message_ar,
                    suggestion_ar=f.suggestion_ar,
                    status=status,
                    action_ar=action,
                )
            )
        fixed_sha = hashlib.sha256(current.encode("utf-8", errors="replace")).hexdigest()[:16]
        return FixResult(
            path=filename,
            changed=current != source,
            fixed_source=current,
            score_before=base.score,
            score_after=after.score,
            verdict_before_ar=base.verdict_ar,
            verdict_after_ar=after.verdict_ar,
            counts_before=base.counts,
            counts_after=after.counts,
            outcomes=outcomes,
            edits=applied_all,
            source_sha256=sha,
            fixed_sha256=fixed_sha,
            seconds=time.perf_counter() - started,
        )

    # --------------------------------------------------------------- الملف
    def fix_file(self, path: str | Path) -> FixResult:
        """إصلاح ملف واحد من القرص مع رسائل عربية لأي عائق قراءة."""
        p = Path(path)
        if not p.is_file():
            return _error_result(str(p), f"الملف غير موجود: {p}")
        try:
            raw = p.read_bytes()
        except OSError as exc:
            return _error_result(str(p), f"تعذرت قراءة الملف: {exc}")
        if len(raw) > MAX_SOURCE_BYTES:
            return _error_result(
                str(p), f"حجم الملف يتجاوز الحد ({len(raw)} بايت > {MAX_SOURCE_BYTES})"
            )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _error_result(str(p), "ترميز الملف ليس UTF-8 — الإصلاح النصي غير ممكن")
        return self.fix_source(source, str(p))

    # -------------------------------------------------------------- الشجرة
    def fix_path(self, path: str | Path) -> list[FixResult]:
        """إصلاح ملف أو شجرة مجلدات — ترتيب حتمي (فرز المسارات)."""
        p = Path(path)
        if p.is_file():
            return [self.fix_file(p)]
        if not p.is_dir():
            return [_error_result(str(p), f"المسار غير موجود: {p}")]
        py_files = sorted(
            f
            for f in p.rglob("*.py")
            if not any(part in SKIP_PARTS or part.endswith(".egg-info") for part in f.parts)
        )
        return [self.fix_file(f) for f in py_files]


def _error_result(path: str, message_ar: str) -> FixResult:
    return FixResult(
        path=path,
        changed=False,
        fixed_source="",
        score_before=0,
        score_after=0,
        verdict_before_ar="غير قابل للتحليل",
        verdict_after_ar="غير قابل للتحليل",
        parse_error=message_ar,
    )


def summarize_fix(results: list[FixResult]) -> dict[str, Any]:
    """ملخص دفعة إصلاح: ملفات، تعدّل، مصائر الملاحظات، أدنى درجة بعدها."""
    return {
        "schema": SCHEMA,
        "files": len(results),
        "changed_files": sum(1 for r in results if r.changed),
        "fixed": sum(r.fixed_count for r in results),
        "manual": sum(r.manual_count for r in results),
        "open": sum(r.open_count for r in results),
        "fixable_remaining": sum(r.fixable_remaining for r in results),
        "min_score_after": min(
            (r.score_after for r in results if r.parse_error is None), default=0
        ),
    }


def review_of(result: FixResult) -> ReviewResult | None:
    """مراجعة النص بعد الإصلاح — ميسّرة للبوابات والتقارير المقارنة.
    السلسلة الفارغة وحدة صالحة؛ لا نُرجع None إلا عند تعذر التحليل نفسه."""
    if result.parse_error is not None:
        return None
    return ReviewEngine().review_source(result.fixed_source, result.path)


__all__ = [
    "MAX_PASSES",
    "SCHEMA",
    "STATUS_AR",
    "STATUS_FIXED",
    "STATUS_MANUAL",
    "STATUS_OPEN",
    "FixOutcome",
    "FixResult",
    "FixerEngine",
    "review_of",
    "summarize_fix",
    "verdict_for_score",
]
