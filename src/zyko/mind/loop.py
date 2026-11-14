"""zyko.mind.loop — الحلقة الإدراكية الكاملة: هدف عربي ⇒ عمل محروس بذاكرة.

هذا هو «التجميع» الذي وثّقته ``docs/MIND.md`` §6.1: الوحدات الست تعمل
كنظام واحد، وكل انتقال بينها بوابة موثقة في إيصال حتمي بسلسلة sha256:

  1. **الإدراك** — تطبيع وتصنيف ومعايير نجاح (``perception``).
  2. **التخطيط** — خطوات حتمية + استشارة القلب خلف بوابة PII ← RTL
     (``planner``)؛ الخطة المرفوضة توقف كل شيء قبل أي بايت.
  3. **التنفيذ** — تفويض حرفي لمحركات المصنع: ``PipelineEngine`` للبناء،
     والمحدّد الحتمي (classify ← route ← run) للكود القائم — لا إعادة
     تنفيذ ولا مسار موازٍ.
  4. **النقد** — فحص الناتج الفعلي على معايير النجاح (``critic``)؛
     الفجوات ملاحظات عربية لا حكم بالحدس.
  5. **الانعكاس وإعادة المحاولة** — حلقة ذاتية التصحيح موثقة (``reflect``):
     حرّاس مخرجات على كل مرحلة، وملاحظة انعكاس عربية من كل فشل تعود
     مدخلًا للمحاولة التالية تحت ميزانية صارمة — جولات موثقة لا مكررة.
  6. **الذاكرة** — حالة المشروع الدائمة ودروسه المستخلصة في
     ``<out>/.zyko/mind/``؛ الدروس تُحمَّل في كل جلسة قادمة.

الحتمية: نفس الهدف ونفس البيئة ⇒ نفس الإيصال بالبايت — ``chain_hash``
مشتق من محتوى الخطوات لا من الزمن، و``seconds_total`` خارج السلسلة
موثقًا لا مدخلًا فيها. التشغيل الجاف يوثّق كل البوابات ولا يكتب شيئًا.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.ai.receipt import hash_file
from zyko.mind.autodetect import CoreDecision
from zyko.mind.core import DeterministicCore, ModelCore, core_report
from zyko.mind.critic import CriticReport, critique
from zyko.mind.global_memory import GlobalMemory
from zyko.mind.memory import MindMemory
from zyko.mind.perception import perceive
from zyko.mind.planner import PLAN_GATE_TITLE, build_plan
from zyko.mind.reflect import (
    STAGE_CRITIC,
    STAGE_PLAN,
    Reflection,
    RetryBudget,
    condense_feedback,
    fallback_note,
    gate_verdict_summary,
    guard_execution,
    guard_feedback,
    guard_perception,
    guard_plan,
    reflect_note,
)
from zyko.pipeline.engine import MAX_DESCRIPTION_LEN, PipelineEngine
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.session import ToolSession

RECEIPT_SCHEMA = "zyko.mind/receipt-v1"
DEFAULT_FAIL_UNDER = 75
DEFAULT_ROUNDS = 2
# argv تشغيل الاختبارات الحقيقية في جولة التحسين — أول token من القائمة
# البيضاء المشتقة من المفسر الفعلي، والباقي ثابت موثق
TESTS_ARGV_TAIL = ("-m", "pytest", "-q")
MAX_DISCOVERED_TEST_FILES = 64  # سقف كشف ملفات الاختبار — فحص حتمي محدود


# ----------------------------------------------------------------- الإيصال
@dataclass
class MindStepRecord:
    """خطوة موثقة واحدة: اسمها وحكمها ودليلها العربي وبصمات إثباتها."""

    step: str
    title_ar: str
    ok: bool
    exit_code: int
    details_ar: str
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """ممثل JSON كامل للخطوة — مفاتيح ثابتة الترتيب."""
        return {
            "step": self.step,
            "title_ar": self.title_ar,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "details_ar": self.details_ar,
            "evidence": dict(sorted(self.evidence.items())),
        }


@dataclass
class MindReceipt:
    """إيصال الحلقة الكاملة — حتمي بالبايت في كل حقله ما عدا الزمن."""

    goal: str
    core: dict
    core_decision: dict
    out: str
    rounds: int
    rounds_ran: int
    fail_under: int
    dry_run: bool
    kind: str
    confidence: float
    plan_accepted: bool
    plan_text: str
    ok: bool = True
    failed_step: str | None = None
    steps: list[MindStepRecord] = field(default_factory=list)
    lessons_loaded: tuple[str, ...] = ()
    lessons_learned: tuple[str, ...] = ()
    global_lessons_loaded: tuple[str, ...] = ()  # عابرة للمشاريع — خارج السلسلة (حالة بيئية)
    global_session_seq: int | None = None  # seq في دفتر الجلسات — خارج السلسلة
    gaps_ar: tuple[str, ...] = ()
    reflections: list[dict] = field(default_factory=list)  # انعكاسات موثقة بترتيب زمني
    budget: dict = field(default_factory=dict)  # ميزانية إعادة المحاولة عند الختام
    chain_hash: str = ""
    seconds_total: float = 0.0

    def to_dict(self) -> dict:
        """ممثل JSON كامل للإيصال — قابل للتحقق دون ثقة."""
        return {
            "schema": RECEIPT_SCHEMA,
            "goal": self.goal,
            "core": self.core,
            "core_decision": self.core_decision,
            "out": self.out,
            "rounds": self.rounds,
            "rounds_ran": self.rounds_ran,
            "fail_under": self.fail_under,
            "dry_run": self.dry_run,
            "kind": self.kind,
            "confidence": self.confidence,
            "plan_accepted": self.plan_accepted,
            "plan_text": self.plan_text,
            "ok": self.ok,
            "failed_step": self.failed_step,
            "steps": [s.to_dict() for s in self.steps],
            "lessons_loaded": list(self.lessons_loaded),
            "lessons_learned": list(self.lessons_learned),
            "global_lessons_loaded": list(self.global_lessons_loaded),
            "global_session_seq": self.global_session_seq,
            "gaps_ar": list(self.gaps_ar),
            "reflections": [dict(r) for r in self.reflections],
            "budget": dict(self.budget),
            "chain_hash": self.chain_hash,
        }

    def to_json(self) -> str:
        """تسلسل JSON حتمي — مفاتيح مفرزة ومحرف اتجاه آمن."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def to_md(self) -> str:
        """تقرير عربي مقروء للإيصال — يُكتب داخل ``.zyko/mind/``."""
        lines = ["# إيصال الحلقة الإدراكية — ZYKO Mind", ""]
        lines.append(f"الهدف: {self.goal}")
        lines.append(f"النوع: {self.kind} (ثقة {self.confidence:.2f}) — القلب: {self.core['name']}")
        if self.core_decision:
            lines.append(
                f"قرار القلب: {self.core_decision['selected']} ({self.core_decision['mode']})"
                f" — {self.core_decision['reason_ar']}"
            )
        verdict = "مقبول" if self.ok else f"مرفوض عند «{self.failed_step}»"
        lines.append(f"الحكم: {verdict} — جولات منفذة {self.rounds_ran}/{self.rounds}")
        lines.append("")
        lines.append("| البوابة | الحكم | الدليل |")
        lines.append("|:---|:---:|:---|")
        for s in self.steps:
            state = "نجاح" if s.ok else "فشل"
            lines.append(f"| {s.title_ar} | {state} | {s.details_ar} |")
        if self.gaps_ar:
            lines.append("")
            lines.append("## فجوات النقد")
            lines.extend(f"- {g}" for g in self.gaps_ar)
        if self.reflections:
            lines.append("")
            lines.append("## الانعكاسات وإعادة المحاولة")
            lines.append(
                f"الميزانية المستهلكة: {self.budget.get('total_used', 0)}"
                f" من سقف {self.budget.get('total_cap', 0)} إعادة"
            )
            for r in self.reflections:
                state = "أُعيدت المحاولة" if r.get("retried") else "توقفت الحلقة"
                lines.append(
                    f"- «{r.get('stage')}» المحاولة {r.get('attempt')} — {state}:"
                    f" {r.get('trigger_ar')}"
                )
        if self.lessons_learned:
            lines.append("")
            lines.append("## دروس تعلمتها هذه الجلسة")
            lines.extend(f"- {g}" for g in self.lessons_learned)
        lines.append("")
        lines.append(f"سلسلة الأدلة: `{self.chain_hash[:16]}…`")
        return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- الحلقة
class MindLoop:
    """الحلقة الإدراكية الموثقة: إدراك ← تخطيط ← تنفيذ ← نقد ← تحسين ← ذاكرة."""

    def __init__(
        self,
        core: ModelCore | None = None,
        *,
        rounds: int = DEFAULT_ROUNDS,
        fail_under: int = DEFAULT_FAIL_UNDER,
        core_decision: CoreDecision | dict | None = None,
        budget: RetryBudget | None = None,
        tools: ToolSession | None = None,
    ) -> None:
        self.core: ModelCore = core if core is not None else DeterministicCore()
        self.rounds = max(1, int(rounds))
        self.fail_under = int(fail_under)
        # ميزانية إعادة المحاولة: سقوف معلنة لا حدس — كل استهلاك موثق بالإيصال
        self.budget = budget if budget is not None else RetryBudget()
        # جلسة الأدوات المعزولة (الأولوية 3): جولة التحسين تشغّل اختبارات
        # حقيقية تحت عقد صلاحيات وسجل تدقيق — بلا جلسة يبقى السلوك
        # الحتمي الأصلي (المُصلِّح الحتمي فقط) دون أي تغيير
        self.tools = tools
        # قرار اختيار القلب يدخل الإيصال وسلسلة الأدلة — الكشف التلقائي
        # جزء موثق من القصة لا حدس صامت. القلب الحتمي بدون قرار يعطي {}.
        self.core_decision: dict = (
            dict(core_decision.to_dict())
            if isinstance(core_decision, CoreDecision)
            else dict(core_decision or {})
        )

    # ------------------------------------------------------------ الحرس
    def _structural_block(
        self,
        receipt: MindReceipt,
        step: str,
        title_ar: str,
        details_ar: str,
        started: float,
    ) -> MindReceipt:
        """فشل هيكلي آمن: يُوثَّق ويرجع — لا استثناء ولا كتابة."""
        receipt.steps.append(
            MindStepRecord(
                step=step,
                title_ar=title_ar,
                ok=False,
                exit_code=2,
                details_ar=details_ar,
            )
        )
        receipt.ok = False
        receipt.failed_step = step
        receipt.chain_hash = self._chain_hash(receipt)
        receipt.seconds_total = time.perf_counter() - started
        return receipt

    def _chain_hash(self, receipt: MindReceipt) -> str:
        """بصمة الإيصال الحتمية — محتوى الخطوات لا الزمن."""
        payload = {
            "schema": RECEIPT_SCHEMA,
            "goal": receipt.goal,
            "core": receipt.core,
            "core_decision": receipt.core_decision,
            "out": receipt.out,
            "rounds": receipt.rounds,
            "rounds_ran": receipt.rounds_ran,
            "fail_under": receipt.fail_under,
            "dry_run": receipt.dry_run,
            "kind": receipt.kind,
            "plan_accepted": receipt.plan_accepted,
            "steps": [
                {"step": s.step, "ok": s.ok, "exit_code": s.exit_code} for s in receipt.steps
            ],
            "lessons_learned": list(receipt.lessons_learned),
            "gaps_ar": list(receipt.gaps_ar),
            "reflections": list(receipt.reflections),
            "budget": dict(receipt.budget),
            "ok": receipt.ok,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------ الحلقة
    def run(
        self,
        goal: object,
        out_dir: str | Path,
        *,
        write: bool = True,
    ) -> MindReceipt:
        """شغّل الحلقة كاملة وأعد الإيصال — بلا أي استثناء خارج."""
        started = time.perf_counter()
        out_path = Path(out_dir)
        receipt = MindReceipt(
            goal=goal if isinstance(goal, str) else repr(goal),
            core=core_report(self.core),
            core_decision=self.core_decision,
            out=out_path.name,
            rounds=self.rounds,
            rounds_ran=0,
            fail_under=self.fail_under,
            dry_run=not write,
            kind="UNKNOWN",
            confidence=0.0,
            plan_accepted=False,
            plan_text="",
        )

        # ---- 0) حرس المدخلات قبل أي عمل — عقد الحلقة نفسه بلا مساومة
        if not isinstance(goal, str):
            return self._structural_block(
                receipt,
                "goal",
                "حرس المدخلات",
                "الهدف يجب أن يكون نصًا عربيًا — وصل نوع غير نصي",
                started,
            )
        desc = " ".join(goal.split())
        if not desc:
            return self._structural_block(
                receipt, "goal", "حرس المدخلات", "الهدف فارغ — اكتب وصفًا عربيًا للمطلوب", started
            )
        if len(desc) > MAX_DESCRIPTION_LEN:
            return self._structural_block(
                receipt,
                "goal",
                "حرس المدخلات",
                f"الهدف طويل جدًا ({len(desc)} محرفًا) — الحد {MAX_DESCRIPTION_LEN} محرفًا",
                started,
            )
        if write and out_path.exists() and any(out_path.iterdir()):
            return self._structural_block(
                receipt,
                "goal",
                "حرس المدخلات",
                f"مجلد الإخراج «{out_path.name}» موجود وغير فارغ — اكتب مجلدًا جديدًا فارغًا",
                started,
            )

        # ---- 1) الإدراك: تصنيف + معايير نجاح — حتمي بلا نموذج، وحارس يفحص ناتجه
        perception = perceive(desc)
        receipt.kind = perception.kind.value
        receipt.confidence = perception.classification.confidence
        # الذاكرة عند الإدراك: دروس المشروع أولًا ثم العابرة للمشاريع بلا تكرار —
        # القراءة من الذاكرة العابرة آمنة في التشغيل الجاف (لا كتابة).
        project_lessons = MindMemory(out_path).load_lessons() if out_path.exists() else ()
        global_memory = GlobalMemory()
        receipt.global_lessons_loaded = global_memory.load_lessons()
        receipt.lessons_loaded = project_lessons + tuple(
            lesson for lesson in receipt.global_lessons_loaded if lesson not in project_lessons
        )
        p_guard = guard_perception(perception)
        receipt.steps.append(
            MindStepRecord(
                step="perceive",
                title_ar="الإدراك (تطبيع ← تصنيف ← معايير نجاح)",
                ok=p_guard.ok,
                exit_code=0 if p_guard.ok else 1,
                details_ar=(
                    f"النوع {perception.kind.value} بثقة {perception.classification.confidence:.2f} — "
                    f"{len(perception.criteria)} معايير نجاح، ودروس محملة: {len(receipt.lessons_loaded)}"
                    if p_guard.ok
                    else f"حرس الإدراك رفض الناتج — {p_guard.reason_ar}"
                ),
            )
        )
        if not p_guard.ok:
            # لا استشارة قلب ولا خطة لمهمة غير مفهومة — رفض مبكر موثق
            return self._finish(receipt, started)

        # ---- 2) بوابة الخطة مع حلقة الانعكاس: رفض ⇒ درس ⇒ استشارة جديدة
        # الموجة 28: غذاء الرسم البياني — جوار الملف المستهدف للخطة،
        # مستورَد كسولاً على بنية المشروع، وفراغه لا يغيّر الطلب بالبايت
        graph_note = ""
        if perception.is_existing_task:
            from zyko.reviewer.repo_graph import neighborhood_note_for

            graph_note = neighborhood_note_for(perception.target_path or "")
        plan = build_plan(perception, self.core, graph_note=graph_note)
        attempt = 1
        guard = guard_plan(plan, perception)
        while not (plan.accepted and guard.ok):
            trigger_ar = (
                gate_verdict_summary(plan.verdicts) if not plan.accepted else guard.reason_ar
            )
            note = reflect_note(STAGE_PLAN, reason_ar=trigger_ar, gaps=(), attempt=attempt)
            feedback = note if guard_feedback(note).ok else fallback_note()
            will_retry = self.budget.can_retry(STAGE_PLAN)
            receipt.reflections.append(
                Reflection(
                    stage=STAGE_PLAN,
                    attempt=attempt,
                    trigger_ar=trigger_ar,
                    feedback_ar=feedback,
                    retried=will_retry,
                ).to_dict()
            )
            receipt.steps.append(
                MindStepRecord(
                    step="plan",
                    title_ar=f"{PLAN_GATE_TITLE} — المحاولة {attempt}",
                    ok=False,
                    exit_code=1,
                    details_ar=trigger_ar
                    + (
                        " — أُعيدت المحاولة بملاحظة الدرس"
                        if will_retry
                        else " — توقفت الحلقة: نفدت ميزانية الخطة"
                    ),
                )
            )
            if not will_retry:
                break
            self.budget.consume(STAGE_PLAN)
            attempt += 1
            plan = build_plan(perception, self.core, feedback=feedback, graph_note=graph_note)
            guard = guard_plan(plan, perception)
        receipt.plan_accepted = bool(plan.accepted and guard.ok)
        receipt.plan_text = plan.text_ar() if receipt.plan_accepted else ""
        if receipt.plan_accepted:
            receipt.steps.append(
                MindStepRecord(
                    step="plan",
                    title_ar=PLAN_GATE_TITLE,
                    ok=True,
                    exit_code=0,
                    details_ar="؛ ".join(v.details_ar for v in plan.verdicts if v.details_ar)
                    or "خطة مقبولة",
                )
            )
        else:
            return self._finish(receipt, started)

        # ---- 3) التنفيذ: تفويض حرفي لمحركات المصنع — لا مسار موازٍ
        if perception.kind.value == "GENERATE":
            result = PipelineEngine().run(
                perception.goal, out_path, git_init=False, rounds=self.rounds, write=write
            )
            score_after: int | None = result.min_score_after
            exec_ok = bool(result.ok) and (
                result.min_score_after >= self.fail_under if write else True
            )
            if result.ok and exec_ok and write:
                details = (
                    f"أدنى درجة بعد الإصلاح {result.min_score_after} ≥ الحد {self.fail_under}"
                    f" — جولات المراجعة←الإصلاح: {result.rounds_ran}"
                )
            elif result.ok and not write:
                details = (
                    f"تشغيل جاف سليم هيكليًا — حد {self.fail_under} يُفحص عند وضع الكتابة"
                    f" — ملفات مقترحة: {len(result.files)}"
                )
            elif not result.ok:
                details = f"فشل هيكلي في المرحلة «{result.failed_stage}»: {result.error_ar}"
            else:
                details = (
                    f"أدنى درجة {result.min_score_after} دون الحد {self.fail_under}"
                    f" — تبقى {result.open_total + result.manual_total} ملاحظة"
                )
            evidence = {
                rel: hash_file(out_path / rel)
                for rel in sorted(set(result.files) | set(result.written))
                if (out_path / rel).is_file()
            }
            exec_record = MindStepRecord(
                step="execute",
                title_ar="التنفيذ (محرك الحلقة: توليد ← مراجعة ← إصلاح)",
                ok=exec_ok,
                exit_code=result.exit_code
                if result.ok and exec_ok
                else (2 if not result.ok else 1),
                details_ar=details,
                evidence=evidence,
            )
            exec_guard = guard_execution(exec_record, out_path, write=write)
            if exec_record.ok and not exec_guard.ok:
                exec_record.ok = False
                exec_record.exit_code = 2
                exec_record.details_ar = f"حرس التنفيذ رفض — {exec_guard.reason_ar}"
            receipt.steps.append(exec_record)
            receipt.rounds_ran = max(1, result.rounds_ran)
            if not exec_record.ok and not result.ok:
                return self._finish(receipt, started)
        else:
            target = perception.target_path or ""
            target_path = Path(target) if target else None
            if target_path is None or not target_path.is_file():
                receipt.steps.append(
                    MindStepRecord(
                        step="execute",
                        title_ar="التنفيذ (الكود القائم)",
                        ok=False,
                        exit_code=1,
                        details_ar=(
                            "لم يُعثر على ملف قائم في الهدف — حدّد ملفًا قائمًا "
                            "أو استخدم وصفًا لمشروع جديد"
                        ),
                    )
                )
                return self._finish(receipt, started)
            exec_result = self._run_existing(perception, out_path, write=write)
            existing_guard = guard_execution(exec_result, out_path, write=write)
            if exec_result.ok and not existing_guard.ok:
                exec_result.ok = False
                exec_result.exit_code = 2
                exec_result.details_ar = f"حرس التنفيذ رفض — {existing_guard.reason_ar}"
            receipt.steps.append(exec_result)
            score_after = self._existing_score(target)
            receipt.rounds_ran = 1

        # ---- 4) النقد: معايير النجاح على الناتج الفعلي
        report = self._critique(perception, out_path, score_after, dry_run=not write)
        receipt.gaps_ar = report.gaps_ar
        receipt.steps.append(
            MindStepRecord(
                step="critic",
                title_ar="النقد (معايير النجاح على الناتج الفعلي)",
                ok=report.ok,
                exit_code=0 if report.ok else 1,
                details_ar=report.table_ar() or "لا معايير للفحص",
            )
        )

        # ---- 5) الانعكاس وإعادة المحاولة: فجوات ⇒ درس ⇒ إصلاح ⇒ نقد ثانٍ
        # الكود القائم: جولة توثيق واحدة فقط — إعادة أعمى لمسار حتمي لا
        # تغيّر مدخلاته رفض موثقة لا صامتة. البناء المولّد: حلقة كاملة
        # تحت ميزانية النقد والجولات معًا، كل جولة بانعكاس موثق.
        final_report = report
        attempt = 1
        if (
            not final_report.ok
            and perception.kind.value != "GENERATE"
            and self.rounds > 1
            and receipt.rounds_ran < self.rounds
        ):
            receipt.reflections.append(
                Reflection(
                    stage=STAGE_CRITIC,
                    attempt=1,
                    trigger_ar=condense_feedback("", final_report.gaps_ar, budget=200),
                    feedback_ar="لا إعادة للمسار القائم — الإصلاح عبر خطوات الخطة نفسها",
                    retried=False,
                ).to_dict()
            )
            receipt.rounds_ran += 1
            final_report = self._refine(perception, out_path, receipt, score_after)
            receipt.gaps_ar = final_report.gaps_ar
        while (
            not final_report.ok
            and perception.kind.value == "GENERATE"
            and receipt.rounds_ran < self.rounds
            and self.budget.can_retry(STAGE_CRITIC)
        ):
            trigger_ar = condense_feedback("", final_report.gaps_ar, budget=200)
            note = reflect_note(
                STAGE_CRITIC,
                reason_ar=trigger_ar,
                gaps=final_report.gaps_ar,
                attempt=attempt,
            )
            feedback = note if guard_feedback(note, final_report.gaps_ar).ok else fallback_note()
            self.budget.consume(STAGE_CRITIC)
            receipt.reflections.append(
                Reflection(
                    stage=STAGE_CRITIC,
                    attempt=attempt,
                    trigger_ar=trigger_ar,
                    feedback_ar=feedback,
                    retried=True,
                ).to_dict()
            )
            receipt.rounds_ran += 1
            final_report = self._refine(perception, out_path, receipt, score_after)
            receipt.gaps_ar = final_report.gaps_ar
            attempt += 1
        if not final_report.ok and attempt > 1 and perception.kind.value == "GENERATE":
            # سبب التوقف موثق صريحًا: ميزانية النقد أو الجولات نفدت والفجوات باقية
            receipt.reflections.append(
                Reflection(
                    stage=STAGE_CRITIC,
                    attempt=attempt,
                    trigger_ar=condense_feedback("", final_report.gaps_ar, budget=200),
                    feedback_ar="توقفت الحلقة — نفدت ميزانية النقد أو الجولات والفجوات باقية",
                    retried=False,
                ).to_dict()
            )

        # ---- 6) الذاكرة: حالة دائمة + دروس مستخلصة من فجوات النقد
        self._remember(perception, out_path, receipt, final_report, write=write)

        # ---- الحكم النهائي: آخر سجل لكل بوابة يقرر — في _finish
        return self._finish(receipt, started)

    # ------------------------------------------------------------ الوضع القائم
    def _run_existing(self, perception, out_path: Path, *, write: bool):
        """مسار الكود القائم: عقل ``zyko do`` الحتمي كاملًا على الملف الفعلي."""
        from zyko.orchestrator import classify, extract_context, route
        from zyko.orchestrator.run import run as orchestrator_run
        from zyko.orchestrator.run import step_summary_ar

        desc = perception.goal
        classification = classify(desc)
        context = extract_context(desc)
        plan = route(classification, context=context)
        target = context.get("path") or ""
        sha_before = hash_file(Path(target))
        result = orchestrator_run(plan, dry_run=not write)
        parts = [
            f"التصنيف {classification.task.value} — ثقة {classification.confidence:.2f}",
            f"الخطة ({len(result.steps)} خطوة على {target})",
        ]
        for index, step_result in enumerate(result.steps, start=1):
            state = "نجحت" if step_result.ok else "فشلت"
            summary = (
                step_summary_ar(step_result.output)
                if step_result.ok
                else (step_result.error_ar or "فشل")
            )
            parts.append(f"{index}. [{step_result.step.tool}] {state}: {summary}")
        parts.append(f"سلسلة الأدلة chain_hash {result.receipt['chain_hash'][:16]}…")
        exec_ok = bool(result.steps) and result.ok
        evidence = {target: sha_before}
        if write:
            sha_after = hash_file(Path(target))
            if sha_after != sha_before:
                evidence[target] = sha_after
                parts.append(f"البصمة تغيّرت ({sha_before[:12]}… ← {sha_after[:12]}…)")
        return MindStepRecord(
            step="execute",
            title_ar="التنفيذ (الكود القائم عبر المحدّد الحتمي)",
            ok=exec_ok,
            exit_code=0 if exec_ok else 2,
            details_ar="؛ ".join(parts),
            evidence=evidence,
        )

    def _existing_score(self, target: str) -> int | None:
        """درجة الملف القائم — المراجعة قراءة فقط فتُقاس في الوضعين بأمانة."""
        try:
            from zyko.reviewer.engine import ReviewEngine

            return ReviewEngine().review_file(target).score
        except Exception:  # noqa: BLE001 — فشل القياس لا يخرج من الحلقة
            return None

    # ------------------------------------------------------------ النقد والتحسين
    # ------------------------------------------------------------ الأدوات
    def _tools_contract_for(self, out_path: Path) -> PermissionContract:
        """عقد أدوات مشتق لجذر الناتج — قائمة بيضاء تشمل المفسر الفعلي.

        العقد المشتق يرث سقوف جلسة الأدوات (مهلة، مخرجات، حجم) ولا يرث
        الكتابة: جولة الاختبارات تشغّل لا تُعدّل — و``allow_patch`` يبقى
        صفرًا هنا فلا اختبار يصل إلى أداة الرقعة عبر هذا المسار.
        """
        base = self.tools.contract
        interpreter = (Path(sys.executable).stem.lower() or "python").replace(".exe", "")
        commands = tuple(dict.fromkeys((interpreter, *base.allowed_commands)))
        return PermissionContract.for_roots(
            out_path,
            allow_run_tests=True,
            allowed_commands=commands,
            max_file_bytes=base.max_file_bytes,
            max_output_chars=base.max_output_chars,
            timeout_s=base.timeout_s,
        )

    def _run_real_tests(self, out_path: Path, *, write: bool):
        """جولة التحسين تشغّل اختبارات حقيقية تحت العقد — أو توثق تخطيها.

        الكشف حتمي مسقوف (``test_*.py`` و``*_test.py``)، والتشغيل عبر
        جلسة مشتقة تشترك في سجل تدقيق الجلسة الأصلية — كل محاولة موثقة
        في السلسلة نفسها. النتيجة خطوة موثقة في الإيصال: خروج غير صفر
        يفشل البوابة فعلًا — الاختبارات الحقيقية حكم لا زينة.
        """
        if self.tools is None:
            return None
        if not write:
            return MindStepRecord(
                step="tools",
                title_ar="الأدوات المعزولة (اختبارات حقيقية)",
                ok=True,
                exit_code=0,
                details_ar="تخطٍّ — تشغيل جاف لا ينفّذ عمليات فرعية",
            )
        if not out_path.is_dir():
            return MindStepRecord(
                step="tools",
                title_ar="الأدوات المعزولة (اختبارات حقيقية)",
                ok=True,
                exit_code=0,
                details_ar="لا مجلد ناتج — لا اختبارات تُشغَّل",
            )
        candidates = sorted(
            {
                p
                for p in out_path.rglob("*.py")
                if p.name.startswith("test_") or p.name.endswith("_test.py")
            }
        )
        if not candidates:
            return MindStepRecord(
                step="tools",
                title_ar="الأدوات المعزولة (اختبارات حقيقية)",
                ok=True,
                exit_code=0,
                details_ar="لا ملفات اختبار في الناتج — لا تشغيل حقيقي يُدَّعى",
            )
        contract = self._tools_contract_for(out_path)
        derived = ToolSession(contract, audit_log=self.tools.audit)
        interpreter = (Path(sys.executable).stem.lower() or "python").replace(".exe", "")
        result = derived.run_tests(argv=[interpreter, *TESTS_ARGV_TAIL], cwd=out_path)
        shown = min(len(candidates), MAX_DISCOVERED_TEST_FILES)
        return MindStepRecord(
            step="tools",
            title_ar="الأدوات المعزولة (اختبارات حقيقية تحت عقد صلاحيات)",
            ok=result.ok,
            exit_code=result.exit_code,
            details_ar=f"اختبارات حقيقية على {shown} ملف اختبار — {result.reason_ar}",
        )

    def _critique(
        self, perception, out_path: Path, score_after: int | None, *, dry_run: bool = False
    ) -> CriticReport:
        """نقد الناتج على كل المعايير المُدرَكة — فحوص حتمية على القرص."""
        return critique(
            perception,
            out_path,
            score_after=score_after,
            fail_under=self.fail_under,
            target=perception.target_path,
            dry_run=dry_run,
        )

    def _refine(
        self, perception, out_path: Path, receipt: MindReceipt, score_after: int | None
    ) -> CriticReport:
        """جولة تحسين حتمية: إصلاح الملفات المولَّدة ثم نقد ثانٍ — موثقة لا مكررة."""
        if perception.kind.value != "GENERATE":
            receipt.steps.append(
                MindStepRecord(
                    step="refine",
                    title_ar="التحسين (جولة إصلاح ثانية)",
                    ok=False,
                    exit_code=1,
                    details_ar="لا جولة إصلاح ثانية للكود القائم — إصلاحه عبر خطوات الخطة نفسها",
                )
            )
            return self._critique(perception, out_path, score_after)
        from zyko.fixer.engine import FixerEngine

        fixer = FixerEngine()
        fixed_total = 0
        changed_total = 0
        for fix in fixer.fix_path(out_path):
            if fix.changed and fix.fixed_source:
                Path(fix.path).write_text(fix.fixed_source, encoding="utf-8")
                changed_total += 1
            fixed_total += fix.fixed_count
        tests_step = self._run_real_tests(out_path, write=not receipt.dry_run)
        if tests_step is not None:
            receipt.steps.append(tests_step)
        re_report = self._critique(perception, out_path, score_after, dry_run=receipt.dry_run)
        receipt.gaps_ar = re_report.gaps_ar
        receipt.steps.append(
            MindStepRecord(
                step="refine",
                title_ar="التحسين (جولة إصلاح حتمية ثم نقد ثانٍ)",
                ok=re_report.ok,
                exit_code=0 if re_report.ok else 1,
                details_ar=(
                    f"أُصلح {fixed_total} ملاحظة في {changed_total} ملفًا — "
                    f"النقد الثاني: {len(re_report.findings) - len(re_report.gaps_ar)}"
                    f"/{len(re_report.findings)} معيارًا"
                ),
            )
        )
        return re_report

    # ------------------------------------------------------------ الذاكرة
    def _remember(
        self, perception, out_path: Path, receipt: MindReceipt, report: CriticReport, *, write: bool
    ) -> None:
        """اكتب الذاكرة الطبقية — أو وثّق تخطيها الصريح في التشغيل الجاف."""
        if not write:
            receipt.steps.append(
                MindStepRecord(
                    step="memory",
                    title_ar="الذاكرة (حالة دائمة + دروس)",
                    ok=True,
                    exit_code=0,
                    details_ar="تخطٍّ — تشغيل جاف لا يكتب شيئًا على القرص",
                )
            )
            receipt.steps.append(
                MindStepRecord(
                    step="global-memory",
                    title_ar="الذاكرة العابرة للجلسات (دفتر موقّع + دروس عابرة للمشاريع)",
                    ok=True,
                    exit_code=0,
                    details_ar="تخطٍّ — تشغيل جاف لا يوقّع جلسة ولا يكتب درسًا عابرًا",
                )
            )
            return
        memory = MindMemory(out_path)
        evidence = memory.persist(
            {
                "goal": perception.goal,
                "kind": perception.kind.value,
                "confidence": perception.classification.confidence,
                "criteria": [c.text_ar for c in perception.criteria],
                "ok": receipt.ok,
                "fail_under": self.fail_under,
                "gaps": list(receipt.gaps_ar),
            }
        )
        lessons_source = (
            tuple(f"فجوة متكررة تتعلّمها الحلقة: {g}" for g in receipt.gaps_ar)
            if receipt.gaps_ar
            else ("الجلسة اكتملت بلا فجوات — النمط الناجح مرجع للجلسات القادمة",)
        )
        if receipt.reflections:
            retried_count = sum(1 for r in receipt.reflections if r.get("retried"))
            lessons_source = lessons_source + (
                f"الحلقة أعادت المحاولة {retried_count} مرة بعد انعكاس موثق — الفجوة تُعالج في الجولة التالية لا تُخفى",
            )
        learned = memory.learn(lessons_source)
        receipt.lessons_learned = learned
        evidence.update(
            {str(memory.lessons_path): hash_file(memory.lessons_path)}
            if memory.lessons_path.exists()
            else {}
        )
        receipt.steps.append(
            MindStepRecord(
                step="memory",
                title_ar="الذاكرة (حالة دائمة + دروس مستخلصة)",
                ok=True,
                exit_code=0,
                details_ar=(
                    f"حالة المشروع في .zyko/mind/state.json — دروس مكتسبة "
                    f"{len(learned)} من {len(lessons_source)} مرشحة"
                ),
                evidence=evidence,
            )
        )
        # ---- الذاكرة العابرة للجلسات: توقيع في دفتر بسلسلة sha256 + دروس
        # عابرة للمشاريع. آثارها موثقة في الخطوات والإيصال **خارج**
        # chain_hash — لأن seq يعتمد تاريخ الجهاز، حالة بيئية لا مدخلًا فيها.
        global_memory = GlobalMemory()
        g_entry = global_memory.record_session(
            goal=perception.goal,
            project=out_path.name,
            kind=perception.kind.value,
            ok=True,
            lessons_learned=len(learned),
            gaps=len(receipt.gaps_ar),
            reflections=len(receipt.reflections),
            ts=time.time(),
        )
        receipt.global_session_seq = g_entry.seq
        g_learned = global_memory.learn(lessons_source)
        g_evidence = {str(global_memory.ledger_path): g_entry.hash}
        if global_memory.lessons_path.exists():
            g_evidence[str(global_memory.lessons_path)] = hash_file(global_memory.lessons_path)
        receipt.steps.append(
            MindStepRecord(
                step="global-memory",
                title_ar="الذاكرة العابرة للجلسات (دفتر موقّع + دروس عابرة للمشاريع)",
                ok=True,
                exit_code=0,
                details_ar=(
                    f"الجلسة {g_entry.seq} موقّعة في دفتر sha256 — دروس عابرة جديدة "
                    f"{len(g_learned)} من {len(lessons_source)} مرشحة"
                ),
                evidence=g_evidence,
            )
        )

    # ------------------------------------------------------------ الختام
    def _finish(self, receipt: MindReceipt, started: float) -> MindReceipt:
        """أغلق الإيصال: الحكم النهائي + الميزانية + البصمة + الزمن خارج السلسلة.

        عقد الحكم: **آخر سجل لكل بوابة هو الذي يقرر** — المحاولات الوسيطة
        المرفوضة ثم المجتازة تاريخ موثق في الخطوات والانعكاسات لا فشل
        نهائي، كما أن نفاد الميزانية بفشل أخير يبقى فشلًا كاملًا موثقًا.
        """
        final_gates: dict[str, bool] = {}
        for s in receipt.steps:
            final_gates[s.step] = s.ok
        receipt.ok = all(final_gates.values())
        if not receipt.ok:
            receipt.failed_step = next(s.step for s in receipt.steps if not final_gates[s.step])
        receipt.budget = self.budget.to_dict()
        receipt.chain_hash = self._chain_hash(receipt)
        receipt.seconds_total = time.perf_counter() - started
        return receipt


__all__ = [
    "DEFAULT_FAIL_UNDER",
    "DEFAULT_ROUNDS",
    "RECEIPT_SCHEMA",
    "MindLoop",
    "MindReceipt",
    "MindStepRecord",
]
