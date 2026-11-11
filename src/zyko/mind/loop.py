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
  5. **التحسين** — جولة إصلاح حتمية على الناتج المولَّد عند فجوات وجولات
     متبقية (``FixerEngine``) ثم نقد ثانٍ — فتبقى الجولات موثقة لا مكررة.
  6. **الذاكرة** — حالة المشروع الدائمة ودروسه المستخلصة في
     ``<out>/.zyko/mind/``؛ الدروس تُحمَّل في كل جلسة قادمة.

الحتمية: نفس الهدف ونفس البيئة ⇒ نفس الإيصال بالبايت — ``chain_hash``
مشتق من محتوى الخطوات لا من الزمن، و``seconds_total`` خارج السلسلة
موثقًا لا مدخلًا فيها. التشغيل الجاف يوثّق كل البوابات ولا يكتب شيئًا.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.ai.receipt import hash_file
from zyko.mind.critic import CriticReport, critique
from zyko.mind.core import DeterministicCore, ModelCore, core_report
from zyko.mind.memory import MindMemory
from zyko.mind.perception import perceive
from zyko.mind.planner import PLAN_GATE_TITLE, build_plan
from zyko.pipeline.engine import MAX_DESCRIPTION_LEN, PipelineEngine

RECEIPT_SCHEMA = "zyko.mind/receipt-v1"
DEFAULT_FAIL_UNDER = 75
DEFAULT_ROUNDS = 2


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
    gaps_ar: tuple[str, ...] = ()
    chain_hash: str = ""
    seconds_total: float = 0.0

    def to_dict(self) -> dict:
        """ممثل JSON كامل للإيصال — قابل للتحقق دون ثقة."""
        return {
            "schema": RECEIPT_SCHEMA,
            "goal": self.goal,
            "core": self.core,
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
            "gaps_ar": list(self.gaps_ar),
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
    ) -> None:
        self.core: ModelCore = core if core is not None else DeterministicCore()
        self.rounds = max(1, int(rounds))
        self.fail_under = int(fail_under)

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
                receipt, "goal", "حرس المدخلات", "الهدف يجب أن يكون نصًا عربيًا — وصل نوع غير نصي", started
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

        # ---- 1) الإدراك: تصنيف + معايير نجاح — حتمي بلا نموذج
        perception = perceive(desc)
        receipt.kind = perception.kind.value
        receipt.confidence = perception.classification.confidence
        receipt.lessons_loaded = MindMemory(out_path).load_lessons() if out_path.exists() else ()
        receipt.steps.append(
            MindStepRecord(
                step="perceive",
                title_ar="الإدراك (تطبيع ← تصنيف ← معايير نجاح)",
                ok=perception.kind.value != "UNKNOWN",
                exit_code=0 if perception.kind.value != "UNKNOWN" else 1,
                details_ar=(
                    f"النوع {perception.kind.value} بثقة {perception.classification.confidence:.2f} — "
                    f"{len(perception.criteria)} معايير نجاح، ودروس محملة: {len(receipt.lessons_loaded)}"
                ),
            )
        )

        # ---- 2) بوابة الخطة: خطوات حتمية + استشارة القلب خلف PII ← RTL
        plan = build_plan(perception, self.core)
        receipt.plan_accepted = plan.accepted
        receipt.plan_text = plan.text_ar() if plan.accepted else ""
        receipt.steps.append(
            MindStepRecord(
                step="plan",
                title_ar=PLAN_GATE_TITLE,
                ok=plan.accepted,
                exit_code=0 if plan.accepted else 1,
                details_ar="؛ ".join(v.details_ar for v in plan.verdicts if v.details_ar)
                or "اقتراح مرفوض",
            )
        )
        if not plan.accepted:
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
            receipt.steps.append(
                MindStepRecord(
                    step="execute",
                    title_ar="التنفيذ (محرك الحلقة: توليد ← مراجعة ← إصلاح)",
                    ok=exec_ok,
                    exit_code=result.exit_code if result.ok and exec_ok else (2 if not result.ok else 1),
                    details_ar=details,
                    evidence=evidence,
                )
            )
            receipt.rounds_ran = max(1, result.rounds_ran)
            if not exec_ok and not result.ok:
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

        # ---- 5) التحسين: جولة إصلاح حتمية عند فجوات وجولات متبقية
        final_report = report
        if not report.ok and self.rounds > 1 and receipt.rounds_ran < self.rounds:
            receipt.rounds_ran += 1
            final_report = self._refine(perception, out_path, receipt, score_after)

        # ---- 6) الذاكرة: حالة دائمة + دروس مستخلصة من فجوات النقد
        self._remember(perception, out_path, receipt, final_report, write=write)

        # ---- الحكم النهائي: كل البوابات الخمس أخضر
        receipt.ok = all(s.ok for s in receipt.steps)
        if not receipt.ok:
            receipt.failed_step = next(s.step for s in receipt.steps if not s.ok)
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
                step_summary_ar(step_result.output) if step_result.ok else (step_result.error_ar or "فشل")
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
    def _critique(self, perception, out_path: Path, score_after: int | None, *, dry_run: bool = False) -> CriticReport:
        """نقد الناتج على كل المعايير المُدرَكة — فحوص حتمية على القرص."""
        return critique(
            perception,
            out_path,
            score_after=score_after,
            fail_under=self.fail_under,
            target=perception.target_path,
            dry_run=dry_run,
        )

    def _refine(self, perception, out_path: Path, receipt: MindReceipt, score_after: int | None) -> CriticReport:
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

    # ------------------------------------------------------------ الختام
    def _finish(self, receipt: MindReceipt, started: float) -> MindReceipt:
        """أغلق الإيصال: الحكم + البصمة + الزمن خارج السلسلة."""
        receipt.ok = all(s.ok for s in receipt.steps)
        if not receipt.ok:
            receipt.failed_step = next(s.step for s in receipt.steps if not s.ok)
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
