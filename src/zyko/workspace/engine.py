"""zyko.workspace.engine — المحرك على أرض الواقع: مراجعة وإصلاح مشروع قائم.

المرحلة 5 (D73–90) من خطة الـ90 يوماً — الشريحة الأخيرة: حتى الآن كان
المحرك يعمل على شيفرة وَلَدَها هو نفسه (المولّد ثم الحلقة). هذا الملف
يفتح المحرك على **أي مشروع بايثون قائم على قرصك**: مراجعة الـ38 قاعدة
ثم إصلاح الـ12 مسارًا الآمن ثم إعادة الفحص — بنفس العقود الثلاثة
التي بُنيت عليها المراحل:

- الحتمية: نفس المجلد ⇒ نفس البايتات (include_timing=False)
- الفشل المهيكل: أي مدخل عدائي ⇒ نتيجة موقعة (failed_stage + سبب عربي)
  بلا أي استثناء خارجي — لا انهيار مهما كان المجلد فاسدًا
- كل ملاحظة — أُصلحت أو بقيت — تحمل ``suggestion_ar`` كما وردت من
  المراجع والمُصلِح، بلا إعادة صياغة ولا اختصار

الحذر مع قرص المستخدم أولوية: الافتراضي **لا يكتب شيئًا** (تجربة
جافة)، والكتابة إما نسخة إلى مجلد جديد فارغ أو تعديل موضعي يتطلب
تأكيدًا صريحًا، ولا يُكتب ملف إلا إذا نجت صياغته النهائية من ast.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.fixer.edits import parses
from zyko.fixer.engine import (
    STATUS_FIXED,
    STATUS_MANUAL,
    STATUS_OPEN,
    FixerEngine,
    FixOutcome,
)
from zyko.fixer.fixes import AUTO_FIXABLE, manual_reason_ar
from zyko.reviewer.engine import (
    MAX_SOURCE_BYTES,
    SKIP_PARTS,
    ReviewEngine,
    summarize,
    verdict_for_score,
)

# مخطط الحمولة JSON — يتغير فقط بمراجعة مقصودة مع توثيق في CHANGELOG.
SCHEMA = "zyko.workspace/1"

# أقصى عدد ملفات بايثون يُعالج في التشغيل الواحد (حماية من الأشجار الضخمة).
MAX_FILES = 500

# أقصى عدد جولات مراجعة←إصلاح (المُصلِح الداخلي يسمح بـ3 تمريرات لكل جولة).
MAX_ROUNDS = 3

STAGE_SCAN = "scan"
STAGE_REVIEWER = "reviewer"
STAGE_FIXER = "fixer"
STAGE_WRITE = "write"
STAGE_WORKSPACE = "workspace"

STAGES: tuple[str, ...] = (STAGE_SCAN, STAGE_REVIEWER, STAGE_FIXER, STAGE_WRITE)

STAGE_AR: dict[str, str] = {
    STAGE_SCAN: "المسح",
    STAGE_REVIEWER: "المراجعة",
    STAGE_FIXER: "الإصلاح",
    STAGE_WRITE: "الكتابة",
    STAGE_WORKSPACE: "المحرك",
}

WRITE_NONE = "none"
WRITE_COPY = "copy"
WRITE_INPLACE = "inplace"

FILE_STATUS_FIXED = "fixed"
FILE_STATUS_CLEAN = "clean"
FILE_STATUS_SKIPPED = "skipped"

FILE_STATUS_AR: dict[str, str] = {
    FILE_STATUS_FIXED: "عُدّل وأُصلح",
    FILE_STATUS_CLEAN: "نظيف — بلا تغيير",
    FILE_STATUS_SKIPPED: "تُخُطّي",
}

VERDICT_NO_PY = "لا مراجعة — لا ملفات بايثون في المجلد"
VERDICT_ALL_SKIPPED = "لا مراجعة — كل الملفات غير قابلة للقراءة أو التحليل"

_OPEN_ROUNDS0_AR = "توقف الإصلاح قبل أن يبدأ (جولات=0) — أعد التشغيل بجولة واحدة على الأقل"


@dataclass
class WorkspaceResult:
    """نتيجة تشغيل المحرك على مجلد قائم: ملفات، درجات، مصائر، ومكتوبات."""

    src: str
    ok: bool = True
    failed_stage: str | None = None
    error_ar: str | None = None
    problems: list[str] = field(default_factory=list)
    write_mode: str = WRITE_NONE
    rounds_requested: int = 1
    rounds_ran: int = 0
    files_total: int = 0
    reviewed: int = 0
    skipped: int = 0
    changed_files: int = 0
    written: list[str] = field(default_factory=list)
    fixed_total: int = 0
    manual_total: int = 0
    open_total: int = 0
    min_score_before: int | None = None
    min_score_after: int | None = None
    verdict_ar: str = ""
    notes: list[str] = field(default_factory=list)
    per_file: list[dict[str, Any]] = field(default_factory=list)
    summary_before: dict[str, Any] = field(default_factory=dict)
    summary_after: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    # النصوص النهائية (تشغيلي فقط — لا يدخل to_dict كي تبقى الحمولة حتمية).
    final_sources: dict[str, str] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """اصطلاح المراحل: 0 سليم/بلا مراجعة، 1 ملاحظات متبقية، 2 فشل مهيكل."""
        if not self.ok:
            return 2
        if self.verdict_ar in (VERDICT_NO_PY, VERDICT_ALL_SKIPPED):
            return 0
        return 0 if self.verdict_ar == verdict_for_score(100) else 1

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ok": self.ok,
            "src": self.src,
            "failed_stage": self.failed_stage,
            "error_ar": self.error_ar,
            "problems": list(self.problems),
            "write_mode": self.write_mode,
            "rounds_requested": self.rounds_requested,
            "rounds_ran": self.rounds_ran,
            "files_total": self.files_total,
            "reviewed": self.reviewed,
            "skipped": self.skipped,
            "changed_files": self.changed_files,
            "written": list(self.written),
            "fixed_total": self.fixed_total,
            "manual_total": self.manual_total,
            "open_total": self.open_total,
            "min_score_before": self.min_score_before,
            "min_score_after": self.min_score_after,
            "verdict_ar": self.verdict_ar,
            "notes": list(self.notes),
            "per_file": [dict(f) for f in self.per_file],
            "summary_before": dict(self.summary_before),
            "summary_after": dict(self.summary_after),
        }
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


class WorkspaceEngine:
    """مراجعة + إصلاح حتمي لمجلد بايثون قائم — بلا نموذج وبلا شبكة."""

    def __init__(
        self,
        reviewer: ReviewEngine | None = None,
        fixer: FixerEngine | None = None,
    ) -> None:
        self.reviewer = reviewer or ReviewEngine()
        self.fixer = fixer or FixerEngine()

    # ------------------------------------------------------------- المحرك
    def run(
        self,
        src: object,
        *,
        rounds: int = 1,
        write: str = WRITE_NONE,
        out_dir: str | Path | None = None,
        confirm_inplace: bool = False,
    ) -> WorkspaceResult:
        """نقطة الدخول الحتمية: مجلد ⇒ نتيجة موقعة (بلا أي استثناء خارج)."""
        started = time.perf_counter()

        # ---- 0) مدخلات محروسة قبل أي عمل
        if isinstance(src, bytes):
            return self._fail("", STAGE_SCAN, "المسار يجب أن يكون نصًا أو Path — وصل bytes", started)
        if not isinstance(src, (str, Path)):
            return self._fail(
                "", STAGE_SCAN, "المسار يجب أن يكون نصًا أو Path — وصل نوع غير مسار", started
            )
        src_str = str(src)
        root = Path(src)
        if isinstance(src, str) and not src.strip():
            return self._fail(src_str, STAGE_SCAN, "المسار فارغ — أعطِ مجلد المشروع القائم", started)
        if not root.exists():
            return self._fail(src_str, STAGE_SCAN, f"المجلد غير موجود: {src_str}", started)
        if not root.is_dir():
            return self._fail(
                src_str, STAGE_SCAN, f"المسار ليس مجلدًا (وُجد ملف): {src_str}", started
            )

        rounds_check = self._check_rounds(rounds)
        if isinstance(rounds_check, str):
            return self._fail(src_str, STAGE_WORKSPACE, rounds_check, started)
        eff_rounds, rounds_note = rounds_check

        write_check = self._check_write(write, out_dir, confirm_inplace)
        if isinstance(write_check, str):
            return self._fail(src_str, STAGE_WORKSPACE, write_check, started)
        eff_write, out_root = write_check

        # ---- 1) المسح الحتمي: ملفات بايثون بترتيب ثابت (بلا روابط رمزية)
        try:
            py_files, truncated = _collect_py_files(root)
        except OSError as exc:
            return self._fail(src_str, STAGE_SCAN, f"تعذر مسح المجلد: {exc}", started)
        notes: list[str] = []
        if rounds_note:
            notes.append(rounds_note)
        if truncated:
            notes.append(f"المجلد يضم أكثر من {MAX_FILES} ملف بايثون — عولج أول {MAX_FILES} فقط")

        if not py_files:
            return self._empty(src_str, eff_write, VERDICT_NO_PY, notes, started)

        # ---- 2) القراءة: ترميز غير سليم أو حجم فوق الحد ⇒ تخطٍ موثق لا انهيار
        sources: dict[str, str] = {}
        read_errors: dict[str, str] = {}
        for p in py_files:
            rel = p.relative_to(root).as_posix()
            try:
                raw = p.read_bytes()
            except OSError as exc:
                read_errors[rel] = f"تعذرت قراءة الملف: {exc}"
                continue
            if len(raw) > MAX_SOURCE_BYTES:
                read_errors[rel] = f"حجم الملف يتجاوز الحد ({len(raw)} بايت > {MAX_SOURCE_BYTES})"
                continue
            try:
                sources[rel] = raw.decode("utf-8")
            except UnicodeDecodeError:
                read_errors[rel] = "ترميز الملف ليس UTF-8 — مراجعة نصية غير ممكنة"

        rels = sorted(sources)
        if not rels:
            return self._all_skipped(src_str, eff_write, read_errors, notes, started)

        # ---- 3) المراجعة الأولى
        try:
            before = {p: self.reviewer.review_source(sources[p], p) for p in rels}
        except Exception as exc:  # noqa: BLE001 — عطب مراجع يُصدَر مهيكلاً لا انهيارًا
            return self._fail(
                src_str, STAGE_REVIEWER, f"عطب غير متوقع في المراجع: {type(exc).__name__}", started
            )

        # ---- 4) الإصلاح بجولات متقاربة
        current = {p: sources[p] for p in rels}
        round_results: dict[str, Any] = {}
        rounds_ran = 0
        try:
            for _ in range(eff_rounds):
                rounds_ran += 1
                round_changed = False
                round_results = {}
                for p in rels:
                    fr = self.fixer.fix_source(current[p], p)
                    round_results[p] = fr
                    if fr.changed:
                        current[p] = fr.fixed_source
                        round_changed = True
                if not round_changed:
                    break
        except Exception as exc:  # noqa: BLE001 — عطب مُصلِح يُصدَر مهيكلاً لا انهيارًا
            return self._fail(
                src_str, STAGE_FIXER, f"عطب غير متوقع في المُصلِح: {type(exc).__name__}", started
            )

        # ---- 5) إعادة الفحص بعد الإصلاح
        try:
            after = {p: self.reviewer.review_source(current[p], p) for p in rels}
        except Exception as exc:  # noqa: BLE001 — تصدير مهيكل لا انهيار
            return self._fail(
                src_str,
                STAGE_REVIEWER,
                f"عطب غير متوقع في إعادة الفحص: {type(exc).__name__}",
                started,
            )

        # ---- 6) مصائر ملاحظات المصدر الأصلي — كل ملاحظة تحمل suggestion_ar
        per_file: list[dict[str, Any]] = []
        fixed_total = manual_total = open_total = changed_files = 0
        for p in rels:
            outcomes = _fates_for(before[p], after[p], round_results.get(p), eff_rounds)
            fixed = sum(1 for o in outcomes if o.status == STATUS_FIXED)
            manual = sum(1 for o in outcomes if o.status == STATUS_MANUAL)
            opened = sum(1 for o in outcomes if o.status == STATUS_OPEN)
            fixed_total += fixed
            manual_total += manual
            open_total += opened
            changed = current[p] != sources[p]
            changed_files += 1 if changed else 0
            entry: dict[str, Any] = {
                "path": p,
                "status": FILE_STATUS_FIXED if changed else FILE_STATUS_CLEAN,
                "changed": changed,
                "score_before": before[p].score,
                "score_after": after[p].score,
                "verdict_before_ar": before[p].verdict_ar,
                "verdict_after_ar": after[p].verdict_ar,
                "fixed_count": fixed,
                "manual_count": manual,
                "open_count": opened,
                "outcomes": [o.to_dict() for o in outcomes],
            }
            if before[p].parse_error is not None:
                entry["parse_error_ar"] = before[p].parse_error
            per_file.append(entry)
        for rel, reason in sorted(read_errors.items()):
            per_file.append(_skipped_entry(rel, reason))
        per_file.sort(key=lambda f: f["path"])

        # ---- 7) الكتابة: لا شيء افتراضيًا — نسخة أو تعديل موضعي عند الطلب
        written: list[str] = []
        if eff_write != WRITE_NONE:
            try:
                for p in rels:
                    if current[p] == sources[p]:
                        if eff_write == WRITE_COPY:
                            # نسخ النظيف غير المعدل كي تكون النسخة مرآة كاملة للبايثون
                            target = out_root / p
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(sources[p], encoding="utf-8", newline="\n")
                        continue
                    if not parses(current[p]):
                        continue  # لا يُكتب ما فشل — تحقق أخير قبل اللمس
                    target = (root / p) if eff_write == WRITE_INPLACE else (out_root / p)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(current[p], encoding="utf-8", newline="\n")
                    written.append(p)
            except OSError as exc:
                return self._fail(src_str, STAGE_WRITE, f"تعذر كتابة النسخ المُصلَحة: {exc}", started)
            notes.append(
                "النسخة المكتوبة تشمل ملفات بايثون المعالجة فقط — بقية أنواع الملفات لم تُنسخ"
            )
        final_sources = {p: current[p] for p in rels}

        # ---- 8) الحكم النهائي
        min_before = min((r.score for r in before.values()), default=None)
        min_after = min((r.score for r in after.values()), default=None)
        verdict = verdict_for_score(min_after) if min_after is not None else VERDICT_ALL_SKIPPED

        return WorkspaceResult(
            src=src_str,
            ok=True,
            write_mode=eff_write,
            rounds_requested=rounds,
            rounds_ran=rounds_ran,
            files_total=len(py_files),
            reviewed=len(rels),
            skipped=len(read_errors),
            changed_files=changed_files,
            written=written,
            fixed_total=fixed_total,
            manual_total=manual_total,
            open_total=open_total,
            min_score_before=min_before,
            min_score_after=min_after,
            verdict_ar=verdict,
            notes=notes,
            per_file=per_file,
            summary_before=summarize(list(before.values())),
            summary_after=summarize(list(after.values())),
            seconds=time.perf_counter() - started,
            final_sources=final_sources,
        )

    # --------------------------------------------------------- المساعدات
    @staticmethod
    def _check_rounds(rounds: object) -> tuple[int, str] | str:
        """يتحقق من عدد الجولات: (المفعّل، ملاحظة) أو رسالة خطأ عربية."""
        if isinstance(rounds, bool) or not isinstance(rounds, int):
            return "عدد الجولات يجب أن يكون عددًا صحيحًا"
        if rounds < 0:
            return f"عدد الجولات سالب ({rounds}) — أعطِ 0 للمراجعة دون إصلاح أو 1 لجولة كاملة"
        if rounds > MAX_ROUNDS:
            return (
                MAX_ROUNDS,
                f"طلبت {rounds} جولات — السقف {MAX_ROUNDS}، سُلّم إلى {MAX_ROUNDS}",
            )
        return rounds, ""

    @staticmethod
    def _check_write(
        write: object, out_dir: str | Path | None, confirm_inplace: bool
    ) -> tuple[str, Path | None] | str:
        """يتحقق من نمط الكتابة: (النمط، مجلد الإخراج) أو رسالة عربية."""
        if write not in (WRITE_NONE, WRITE_COPY, WRITE_INPLACE):
            return "نمط الكتابة يجب أن يكون none أو copy أو inplace — وصل قيمة غير معروفة"
        if write == WRITE_COPY:
            if out_dir is None:
                return "نمط النسخ يتطلب مجلد إخراج out_dir — أو استخدم inplace مع التأكيد"
            out_root = Path(out_dir)
            if out_root.exists():
                if not out_root.is_dir():
                    return f"مجلد الإخراج ليس مجلدًا: {out_root}"
                if any(out_root.iterdir()):
                    return (
                        f"مجلد الإخراج «{out_root}» غير فارغ — اختر مجلدًا جديدًا"
                        " حتى لا يُكتب فوق عمل قائم"
                    )
            return WRITE_COPY, out_root
        if write == WRITE_INPLACE:
            if out_dir is not None:
                return "اختر إما نسخًا إلى out_dir أو تعديلًا موضعيًا — لا كليهما معًا"
            if not confirm_inplace:
                return (
                    "التعديل الموضعي يتطلب تأكيدًا صريحًا (confirm_inplace=True"
                    " أو --yes في سطر الأوامر) — كي لا يُمسّ مشروعك بلا إذن"
                )
            return WRITE_INPLACE, None
        if out_dir is not None:
            return "out_dir يُستخدم فقط مع نمط النسخ copy — الافتراضي لا يكتب شيئًا"
        return WRITE_NONE, None

    def _fail(
        self,
        src: str,
        stage: str,
        message_ar: str,
        started: float,
    ) -> WorkspaceResult:
        """فشل مهيكل: نتيجة موقعة برسالة عربية — لا استثناءات خارجية أبدًا."""
        return WorkspaceResult(
            src=src,
            ok=False,
            failed_stage=stage,
            error_ar=message_ar,
            verdict_ar=f"فشل — {STAGE_AR.get(stage, stage)}",
            seconds=time.perf_counter() - started,
        )

    def _empty(
        self,
        src: str,
        eff_write: str,
        verdict: str,
        notes: list[str],
        started: float,
    ) -> WorkspaceResult:
        """مجلد بلا ملفات بايثون: نجاح بلا مراجعة (خروج 0)."""
        return WorkspaceResult(
            src=src,
            ok=True,
            write_mode=eff_write,
            files_total=0,
            verdict_ar=verdict,
            notes=list(notes),
            seconds=time.perf_counter() - started,
        )

    def _all_skipped(
        self,
        src: str,
        eff_write: str,
        read_errors: dict[str, str],
        notes: list[str],
        started: float,
    ) -> WorkspaceResult:
        """وُجدت ملفات لكن كلها غير قابلة للقراءة/التحليل: نجاح بلا مراجعة."""
        per_file = [_skipped_entry(rel, reason) for rel, reason in sorted(read_errors.items())]
        return WorkspaceResult(
            src=src,
            ok=True,
            write_mode=eff_write,
            files_total=len(read_errors),
            skipped=len(read_errors),
            per_file=per_file,
            verdict_ar=VERDICT_ALL_SKIPPED,
            notes=list(notes),
            seconds=time.perf_counter() - started,
        )


def _collect_py_files(root: Path) -> tuple[list[Path], bool]:
    """مسح حتمي: ملفات ``*.py`` بترتيب مساراتها النسبية — بلا روابط رمزية.

    يعيد (القائمة، هل قُطع بسبب السقف). مجلدات النظام المعتادة
    (``__pycache__`` و``.git`` وغيرها) تُتخطى كما في المراجع.
    """
    found: list[tuple[str, Path]] = []
    truncated = False
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            continue  # مجلد غير مقروء: يُتخطى — المسح يكمل ما يستطيع
        for e in entries:
            if e.name in SKIP_PARTS or e.name.endswith(".egg-info"):
                continue
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    stack.append(e)
                elif e.is_file() and e.suffix == ".py":
                    if len(found) >= MAX_FILES:
                        truncated = True
                        stack.clear()
                        break
                    rel = e.relative_to(root).as_posix()
                    found.append((rel, e))
            except OSError:
                continue  # مدخل ينهار عند فحصه: يُتخطى — لا انهيار للمسح
    found.sort(key=lambda item: item[0])
    return [p for _rel, p in found], truncated


def _skipped_entry(rel: str, reason: str) -> dict[str, Any]:
    """سطر موحد لملف تُخُطّي: بلا درجات ولا ملاحظات — سبب عربي واضح."""
    return {
        "path": rel,
        "status": FILE_STATUS_SKIPPED,
        "changed": False,
        "score_before": None,
        "score_after": None,
        "verdict_before_ar": "",
        "verdict_after_ar": "",
        "fixed_count": 0,
        "manual_count": 0,
        "open_count": 0,
        "outcomes": [],
        "reason_ar": reason,
    }


def _fates_for(
    before: Any,
    after: Any,
    last_fix: Any,
    eff_rounds: int,
) -> list[FixOutcome]:
    """مصير كل ملاحظة أصلية: أُصلحت/يدوي/يبقى — بالنص العربي الأصلي."""
    remaining = {f.rule_id for f in after.findings}
    last_by_rule: dict[str, FixOutcome] = {}
    if last_fix is not None:
        last_by_rule = {o.rule_id: o for o in last_fix.outcomes}
    outcomes: list[FixOutcome] = []
    for f in before.findings:
        if f.rule_id not in AUTO_FIXABLE:
            status, action = STATUS_MANUAL, manual_reason_ar(f.rule_id)
        elif f.rule_id not in remaining:
            status, action = STATUS_FIXED, "أُصلح آليًا"
            if f.rule_id in last_by_rule:
                action = last_by_rule[f.rule_id].action_ar
        elif eff_rounds == 0:
            status, action = STATUS_OPEN, _OPEN_ROUNDS0_AR
        elif f.rule_id in last_by_rule:
            keep = last_by_rule[f.rule_id]
            status, action = STATUS_OPEN, keep.action_ar
        else:
            status, action = (
                STATUS_OPEN,
                "لا مسار إصلاح آمن لهذه الحالة بعينها — عالجها يدويًا",
            )
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
    return outcomes


__all__ = [
    "FILE_STATUS_AR",
    "FILE_STATUS_CLEAN",
    "FILE_STATUS_FIXED",
    "FILE_STATUS_SKIPPED",
    "MAX_FILES",
    "MAX_ROUNDS",
    "MAX_SOURCE_BYTES",
    "SCHEMA",
    "STAGES",
    "STAGE_AR",
    "STAGE_FIXER",
    "STAGE_REVIEWER",
    "STAGE_SCAN",
    "STAGE_WORKSPACE",
    "STAGE_WRITE",
    "VERDICT_ALL_SKIPPED",
    "VERDICT_NO_PY",
    "WRITE_COPY",
    "WRITE_INPLACE",
    "WRITE_NONE",
    "WorkspaceEngine",
    "WorkspaceResult",
    "verdict_for_score",
]
