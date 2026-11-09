"""zyko.pipeline.engine — حلقة التغذية الراجعة: توليد ← مراجعة ← إصلاح في أمر واحد.

المرحلة 4 (D59–72) من خطة الـ90 يوماً: تربط المحركات الثلاثة الحتمية
(``zyko.coder`` ثم ``zyko.reviewer`` ثم ``zyko.fixer``) في خط واحد بلا
نموذج وبلا شبكة، فتعيد **مشروعًا مُصلَحًا** لا مشروعًا خامًا:

- المخطط من الوصف العربي (heuristic افتراضيًا، ومخطِّط قابل للحقن)
- التوليد في الذاكرة أولًا: لا يُكتب شيء قبل أن تُراجَع الشيفرة
- الإصلاح بجولات (حتى 3) مع توقف تقاربي حين لا يتغير شيء
- كل ملاحظة — أُصلحت أو بقيت — تحمل ``suggestion_ar`` عربيًا كما هي
  من المراجع والمُصلِح، بلا إعادة صياغة ولا اختصار
- العقد المضمون تعاقديًا: مدخل عدائي ⇒ نتيجة مهيكلة (failed_stage)
  بلا أي استثناء، والمخرجات حتمية بايتيًا (include_timing=False)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zyko.coder.generate import build_all_files, materialize
from zyko.coder.heuristics import draft_plan
from zyko.coder.plan import PlanValidationError, ProjectPlan
from zyko.fixer.engine import (
    STATUS_FIXED,
    STATUS_MANUAL,
    STATUS_OPEN,
    FixerEngine,
    FixOutcome,
)
from zyko.fixer.fixes import AUTO_FIXABLE, manual_reason_ar
from zyko.reviewer.engine import ReviewEngine, summarize, verdict_for_score

# مخطط الحمولة JSON — يتغير فقط بمراجعة مقصودة مع توثيق في CHANGELOG.
SCHEMA = "zyko.pipeline/1"

# سقف طول الوصف العربي المقبول (حماية من المدخلات العدائية الضخمة).
MAX_DESCRIPTION_LEN = 4000

# أقصى عدد جولات مراجعة←إصلاح بعد التوليد (المحرك الداخلي للمُصلِح
# يسمح بـ3 تمريرات في كل جولة، فنادرًا ما تحتاج الحلقة أكثر من جولة).
MAX_ROUNDS = 3

STAGE_CODER = "coder"
STAGE_REVIEWER = "reviewer"
STAGE_FIXER = "fixer"
STAGE_PIPELINE = "pipeline"

STAGES: tuple[str, ...] = (STAGE_CODER, STAGE_REVIEWER, STAGE_FIXER)

STAGE_AR: dict[str, str] = {
    STAGE_CODER: "التوليد",
    STAGE_REVIEWER: "المراجعة",
    STAGE_FIXER: "الإصلاح",
    STAGE_PIPELINE: "الحلقة",
}

VERDICT_NO_PY = "لا مراجعة — لا ملفات بايثون في الناتج"
_OPEN_ROUNDS0_AR = "توقف الإصلاح قبل أن يبدأ (جولات=0) — أعد التشغيل بجولة واحدة على الأقل"


@dataclass
class PipelineResult:
    """نتيجة الحلقة كاملة: مخطط، ملفات، درجات قبل/بعد، ومصائر الملاحظات."""

    description: str
    ok: bool = True
    failed_stage: str | None = None
    error_ar: str | None = None
    problems: list[str] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    files: list[str] = field(default_factory=list)
    py_files: list[str] = field(default_factory=list)
    rounds_requested: int = 1
    rounds_ran: int = 0
    changed_files: int = 0
    fixed_total: int = 0
    manual_total: int = 0
    open_total: int = 0
    min_score_before: int = 0
    min_score_after: int = 0
    verdict_ar: str = ""
    written: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    per_file: list[dict[str, Any]] = field(default_factory=list)
    summary_before: dict[str, Any] = field(default_factory=dict)
    summary_after: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    # النصوص النهائية بعد الإصلاح (تشغيلي فقط — لا يدخل to_dict كي تبقى
    # الحمولة حتمية مضغوطة، وتستفيد منها البوابة وCLI في الاعتدال والكتابة).
    final_sources: dict[str, str] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """اصطلاح المراحل الثلاث: 0 سليم، 1 ملاحظات متبقية، 2 فشل مهيكل."""
        if not self.ok:
            return 2
        if self.verdict_ar == VERDICT_NO_PY:
            return 0
        return 0 if self.verdict_ar == verdict_for_score(100) else 1

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ok": self.ok,
            "description": self.description,
            "failed_stage": self.failed_stage,
            "error_ar": self.error_ar,
            "problems": list(self.problems),
            "plan": self.plan,
            "files": list(self.files),
            "py_files": list(self.py_files),
            "rounds_requested": self.rounds_requested,
            "rounds_ran": self.rounds_ran,
            "changed_files": self.changed_files,
            "fixed_total": self.fixed_total,
            "manual_total": self.manual_total,
            "open_total": self.open_total,
            "min_score_before": self.min_score_before,
            "min_score_after": self.min_score_after,
            "verdict_ar": self.verdict_ar,
            "written": list(self.written),
            "notes": list(self.notes),
            "per_file": [dict(f) for f in self.per_file],
            "summary_before": dict(self.summary_before),
            "summary_after": dict(self.summary_after),
        }
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


class PipelineEngine:
    """حلقة التغذية الراجعة الحتمية: وصف عربي ⇒ مشروع مُراجَع ومُصلَح."""

    def __init__(
        self,
        reviewer: ReviewEngine | None = None,
        fixer: FixerEngine | None = None,
        planner: Callable[[str], ProjectPlan] | None = None,
    ) -> None:
        self.reviewer = reviewer or ReviewEngine()
        self.fixer = fixer or FixerEngine()
        self.planner = planner or draft_plan

    # ------------------------------------------------------------- الحلقة
    def run(
        self,
        description: object,
        out_dir: str | Path,
        *,
        git_init: bool = False,
        rounds: int = 1,
        write: bool = True,
    ) -> PipelineResult:
        """نقطة الدخول الحتمية: وصف ⇒ نتيجة موقعة (بلا أي استثناء خارج)."""
        started = time.perf_counter()

        # ---- 0) مدخلات محروسة قبل أي عمل
        if not isinstance(description, str):
            return self._fail(STAGE_CODER, "الوصف يجب أن يكون نصًا عربيًا — وصل نوع غير نصي", started)
        desc = description.strip()
        if not desc:
            return self._fail(STAGE_CODER, "الوصف فارغ — اكتب وصفًا عربيًا للمشروع المطلوب", started)
        if len(desc) > MAX_DESCRIPTION_LEN:
            return self._fail(
                STAGE_CODER,
                f"الوصف طويل جدًا ({len(desc)} محرفًا) — الحد {MAX_DESCRIPTION_LEN} محرفًا",
                started,
            )
        rounds_check = self._check_rounds(rounds)
        if isinstance(rounds_check, str):
            return self._fail(STAGE_PIPELINE, rounds_check, started)
        eff_rounds, rounds_note = rounds_check

        # ---- 1) المخطط (coder)
        plan: ProjectPlan
        try:
            plan = self.planner(desc)
            problems = plan.validate()
        except PlanValidationError as exc:
            return self._fail(STAGE_CODER, "رُفض المخطط قبل التوليد", started, problems=exc.problems)
        except Exception as exc:  # noqa: BLE001 — عطب مخطِّط يُصدَر مهيكلاً لا انهيارًا
            return self._fail(
                STAGE_CODER, f"عطب غير متوقع في المخطِّط: {type(exc).__name__}", started
            )
        if problems:
            return self._fail(STAGE_CODER, "رُفض المخطط قبل التوليد", started, problems=problems)

        # ---- 2) التوليد (coder) — في الذاكرة أولًا، والقرص عند الطلب
        try:
            tree = build_all_files(plan)
            gen = materialize(plan, Path(out_dir), git_init=git_init) if write else None
        except FileExistsError:
            return self._fail(
                STAGE_CODER,
                f"المجلد «{out_dir}» غير فارغ — اختر مجلدًا جديدًا حتى لا يُكتب فوق عمل قائم",
                started,
            )
        except OSError as exc:
            return self._fail(STAGE_CODER, f"تعذر كتابة المشروع على القرص: {exc}", started)

        files = sorted(tree)
        py_paths = sorted(p for p in files if p.endswith(".py"))
        notes: list[str] = []
        if rounds_note:
            notes.append(rounds_note)
        if gen is not None:
            notes.extend(gen.warnings)

        # ---- 3) المراجعة الأولى (reviewer)
        try:
            before = {p: self.reviewer.review_source(tree[p].content, p) for p in py_paths}
        except Exception as exc:  # noqa: BLE001 — عطب مراجع يُصدَر مهيكلاً لا انهيارًا
            return self._fail(
                STAGE_REVIEWER, f"عطب غير متوقع في المراجع: {type(exc).__name__}", started
            )

        # ---- 4) الإصلاح بجولات متقاربة (fixer)
        current = {p: tree[p].content for p in py_paths}
        round_results: dict[str, Any] = {}
        rounds_ran = 0
        try:
            for _ in range(eff_rounds):
                rounds_ran += 1
                round_changed = False
                round_results = {}
                for p in py_paths:
                    fr = self.fixer.fix_source(current[p], p)
                    round_results[p] = fr
                    if fr.changed:
                        current[p] = fr.fixed_source
                        round_changed = True
                if not round_changed:
                    break
        except Exception as exc:  # noqa: BLE001 — عطب مُصلِح يُصدَر مهيكلاً لا انهيارًا
            return self._fail(
                STAGE_FIXER, f"عطب غير متوقع في المُصلِح: {type(exc).__name__}", started
            )

        # ---- 5) إعادة الفحص بعد الإصلاح (نفس المراجع — قياس التحسّن)
        try:
            after = {p: self.reviewer.review_source(current[p], p) for p in py_paths}
        except Exception as exc:  # noqa: BLE001 — تصدير مهيكل لا انهيار
            return self._fail(
                STAGE_REVIEWER, f"عطب غير متوقع في إعادة الفحص: {type(exc).__name__}", started
            )

        # ---- 6) مصائر ملاحظات المصدر الأصلي — كل ملاحظة تحمل suggestion_ar
        per_file: list[dict[str, Any]] = []
        fixed_total = manual_total = open_total = changed_files = 0
        for p in py_paths:
            outcomes = self._outcomes_for(p, before[p], after[p], round_results.get(p), eff_rounds)
            fixed = sum(1 for o in outcomes if o.status == STATUS_FIXED)
            manual = sum(1 for o in outcomes if o.status == STATUS_MANUAL)
            opened = sum(1 for o in outcomes if o.status == STATUS_OPEN)
            fixed_total += fixed
            manual_total += manual
            open_total += opened
            changed = current[p] != tree[p].content
            changed_files += 1 if changed else 0
            per_file.append(
                {
                    "path": p,
                    "changed": changed,
                    "score_before": before[p].score,
                    "score_after": after[p].score,
                    "verdict_before_ar": before[p].verdict_ar,
                    "verdict_after_ar": after[p].verdict_ar,
                    "parse_error_ar": before[p].parse_error,
                    "fixed_count": fixed,
                    "manual_count": manual,
                    "open_count": opened,
                    "outcomes": [o.to_dict() for o in outcomes],
                }
            )

        # ---- 7) الكتابة النهائية: النسخ المُصلَحة المتحقق منها فقط
        written: list[str] = []
        if write:
            root = Path(out_dir)
            try:
                for p in py_paths:
                    if current[p] != tree[p].content:
                        (root / p).write_text(current[p], encoding="utf-8", newline="\n")
                        written.append(p)
            except OSError as exc:
                return self._fail(STAGE_FIXER, f"تعذر كتابة النسخ المُصلَحة: {exc}", started)
        final_sources = {p: current[p] for p in py_paths}

        # ---- 8) الحكم النهائي
        min_before = min((r.score for r in before.values()), default=100)
        min_after = min((r.score for r in after.values()), default=100)
        verdict = verdict_for_score(min_after) if py_paths else VERDICT_NO_PY

        return PipelineResult(
            description=desc,
            ok=True,
            plan=plan.to_dict(),
            files=files,
            py_files=py_paths,
            rounds_requested=rounds,
            rounds_ran=rounds_ran,
            changed_files=changed_files,
            fixed_total=fixed_total,
            manual_total=manual_total,
            open_total=open_total,
            min_score_before=min_before,
            min_score_after=min_after,
            verdict_ar=verdict,
            written=written,
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

    def _outcomes_for(
        self,
        path: str,
        before: Any,
        after: Any,
        last_fix: Any,
        eff_rounds: int,
    ) -> list[FixOutcome]:
        """مصير كل ملاحظة أصلية: أُصلحت/يدوي/يبقى — بالنص العربي الأصلي."""
        del path  # الموقع ضمن النتيجة يكفي؛ التوقيع موحّد لسهولة الاختبار
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

    def _fail(
        self,
        stage: str,
        message_ar: str,
        started: float,
        problems: list[str] | None = None,
    ) -> PipelineResult:
        """فشل مهيكل: نتيجة موقعة برسالة عربية — لا استثناءات خارجية أبدًا."""
        return PipelineResult(
            description="",
            ok=False,
            failed_stage=stage,
            error_ar=message_ar,
            problems=list(problems or []),
            verdict_ar=f"فشل — {STAGE_AR.get(stage, stage)}",
            seconds=time.perf_counter() - started,
        )


__all__ = [
    "MAX_DESCRIPTION_LEN",
    "MAX_ROUNDS",
    "SCHEMA",
    "STAGES",
    "STAGE_AR",
    "STAGE_CODER",
    "STAGE_FIXER",
    "STAGE_PIPELINE",
    "STAGE_REVIEWER",
    "VERDICT_NO_PY",
    "PipelineEngine",
    "PipelineResult",
    "verdict_for_score",
]
