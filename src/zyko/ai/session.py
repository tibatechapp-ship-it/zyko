"""zyko.ai.session — جلسة الذكاء الموثّقة: هدف عربي ⇒ مشروع عبر البوابات.

الجلسة هي «التجميع» الأول لـ zyko AI فوق المصنع، وكل نداء فيها يمرّ
على بوابة المصنع القابلة للتحقق:

  1) «خطة» — عقل مقيّد بالبوابات يقترح خطة (المخطط الحتمي افتراضيًا)؛
     اقتراح فيه بيان شخصي أو خطأ اتجاه ⇒ رفض فوري وقف قبل أي توليد.
  2) «توليد» — تفويض حرفي لمحرك الحلقة ``PipelineEngine`` (نفس المراجعة
     والإصلاح ونفس الدرجات)، مع حد قبول ``fail_under``.
  3) «خط أساس» — تفويض حرفي لـ ``BaselineEngine``: تسجيل ثم فحص؛ أي
     تراجع ⇒ رفض.
  4) كل خطوة تُوثَّق في الإيصال ببصماتها — لا تجاوز ولا استثناء خارج.

الحتمية: نفس الهدف ونفس بيئة ⇒ نفس الإيصال بالبايت (بلا أزمنة إلا عند
``include_timing``).
"""

from __future__ import annotations

import time
from pathlib import Path

from zyko.ai.brains import Brain, GatedBrain, PlannerBrain
from zyko.ai.receipt import AIReceipt, StepRecord, hash_file
from zyko.baseline.engine import BaselineEngine
from zyko.pipeline.engine import MAX_DESCRIPTION_LEN, PipelineEngine

DEFAULT_FAIL_UNDER = 75


class AISession:
    """منسّق جلسة واحدة: عقل + بوابات + محرك الحلقة + حارس الجودة."""

    def __init__(
        self,
        brain: Brain | None = None,
        *,
        rounds: int = 1,
        fail_under: int = DEFAULT_FAIL_UNDER,
    ) -> None:
        self.brain: Brain = brain if brain is not None else GatedBrain(PlannerBrain())
        self.rounds = rounds
        self.fail_under = fail_under

    # ------------------------------------------------------------ الحرس
    def _structural_block(
        self,
        receipt: AIReceipt,
        step: str,
        title: str,
        details_ar: str,
    ) -> AIReceipt:
        """فشل هيكلي آمن: يُوثَّق ويرجع — لا استثناء ولا كتابة."""
        receipt.add(
            StepRecord(
                step=step,
                title_ar=title,
                ok=False,
                exit_code=2,
                details_ar=details_ar,
            )
        )
        return receipt

    # ------------------------------------------------------------ الجلسة
    def run(
        self,
        goal: object,
        out_dir: str | Path,
        *,
        write: bool = True,
    ) -> AIReceipt:
        """شغّل الجلسة كاملة وأعد الإيصال — بلا أي استثناء خارج."""
        started = time.perf_counter()
        out_path = Path(out_dir)
        receipt = AIReceipt(
            goal=goal if isinstance(goal, str) else repr(goal),
            brain=self.brain.name,
            brain_deterministic=self.brain.deterministic,
            out=out_path.name,
            rounds=self.rounds,
            fail_under=self.fail_under,
            dry_run=not write,
        )

        # ---- 0) حرس المدخلات قبل أي عمل (نفس حرس الحلقة الحرفي)
        if not isinstance(goal, str):
            return self._structural_block(
                receipt, "goal", "حرس المدخلات", "الهدف يجب أن يكون نصًا عربيًا — وصل نوع غير نصي"
            )
        desc = goal.strip()
        if not desc:
            return self._structural_block(
                receipt, "goal", "حرس المدخلات", "الهدف فارغ — اكتب وصفًا عربيًا للمشروع المطلوب"
            )
        if len(desc) > MAX_DESCRIPTION_LEN:
            return self._structural_block(
                receipt,
                "goal",
                "حرس المدخلات",
                f"الهدف طويل جدًا ({len(desc)} محرفًا) — الحد {MAX_DESCRIPTION_LEN} محرفًا",
            )
        if write and out_path.exists() and any(out_path.iterdir()):
            return self._structural_block(
                receipt,
                "out",
                "حرس المدخلات",
                f"مجلد الإخراج «{out_path.name}» موجود وغير فارغ — اكتب مجلدًا جديدًا فارغًا",
            )

        # ---- 1) بوابة الخطة: اقتراح العقل لا يمر إلا عبر PII ثم RTL
        proposal = self.brain.propose(desc)
        if not proposal.accepted:
            failed = next((v for v in proposal.verdicts if not v.passed), None)
            receipt.add(
                StepRecord(
                    step="plan",
                    title_ar="بوابة الخطة (عقل ← PII ← RTL)",
                    ok=False,
                    exit_code=1,
                    details_ar=failed.details_ar if failed else "اقتراح مرفوض",
                )
            )
            receipt.seconds_total = time.perf_counter() - started
            return receipt
        receipt.plan = {"brain": proposal.brain, "text": proposal.text}
        receipt.add(
            StepRecord(
                step="plan",
                title_ar="بوابة الخطة (عقل ← PII ← RTL)",
                ok=True,
                exit_code=0,
                details_ar="؛ ".join(v.details_ar for v in proposal.verdicts if v.details_ar),
            )
        )

        # ---- 2) بوابة التوليد: تفويض حرفي لمحرك الحلقة (بلا إعادة تنفيذ)
        result = PipelineEngine().run(desc, out_path, git_init=False, rounds=self.rounds, write=write)
        receipt.min_score_after = result.min_score_after
        gen_ok = bool(result.ok) and result.min_score_after >= self.fail_under
        if gen_ok:
            details = (
                f"أدنى درجة بعد الإصلاح {result.min_score_after} ≥ الحد {self.fail_under}"
                f" — جولات مراجعة←إصلاح: {result.rounds_ran}"
            )
        elif not result.ok:
            details = f"فشل هيكلي في المرحلة «{result.failed_stage}»: {result.error_ar}"
        else:
            details = (
                f"أدنى درجة بعد الإصلاح {result.min_score_after} دون الحد {self.fail_under}"
                f" — تبقى {result.open_total + result.manual_total} ملاحظة"
            )
        evidence = {
            rel: hash_file(out_path / rel)
            for rel in sorted(result.written)
            if (out_path / rel).is_file()
        }
        receipt.files_written = sorted(result.written)
        receipt.add(
            StepRecord(
                step="generate",
                title_ar="بوابة التوليد (حلقة مراجعة←إصلاح)",
                ok=gen_ok,
                exit_code=result.exit_code if result.ok and gen_ok else (2 if not result.ok else 1),
                details_ar=details,
                evidence=evidence,
            )
        )
        if not gen_ok:
            receipt.seconds_total = time.perf_counter() - started
            return receipt

        # ---- 3) بوابات حارس الجودة (كتابة فقط — التشغيل الجاف لا يسجل)
        if not write:
            receipt.add(
                StepRecord(
                    step="baseline_update",
                    title_ar="بوابة خط الأساس — تسجيل",
                    ok=True,
                    exit_code=0,
                    details_ar="تخطٍّ — تشغيل جاف لا يسجل خط أساس",
                )
            )
            receipt.add(
                StepRecord(
                    step="baseline_check",
                    title_ar="بوابة خط الأساس — فحص",
                    ok=True,
                    exit_code=0,
                    details_ar="تخطٍّ — تشغيل جاف",
                )
            )
            receipt.seconds_total = time.perf_counter() - started
            return receipt

        update = BaselineEngine().update(out_path)
        baseline_rel = str(Path(update.baseline_path).relative_to(out_path)) if update.ok else ""
        receipt.add(
            StepRecord(
                step="baseline_update",
                title_ar="بوابة خط الأساس — تسجيل",
                ok=bool(update.ok),
                exit_code=update.exit_code,
                details_ar=update.verdict_ar or ("؛ ".join(update.problems) if update.problems else "تسجيل خط الأساس"),
                evidence={baseline_rel: hash_file(update.baseline_path)} if update.ok else {},
            )
        )
        if not update.ok:
            self.write_receipt(receipt, out_path)
            receipt.seconds_total = time.perf_counter() - started
            return receipt

        check = BaselineEngine().check(out_path)
        check_ok = check.exit_code == 0
        if check_ok:
            details = "لا تراجع — الحارس أخضر"
        elif check.baseline_status != "ok":
            details = "خط الأساس مفقود بعد التسجيل — رفض احترازي"
        else:
            details = f"تراجع في {check.regressed_files} ملفًا — الجلسة مرفوضة"
        receipt.add(
            StepRecord(
                step="baseline_check",
                title_ar="بوابة خط الأساس — فحص",
                ok=check_ok,
                exit_code=check.exit_code,
                details_ar=details,
            )
        )

        # الإيصال جزء من المشروع نفسه — يُكتب داخل <out>/.zyko دائمًا بعد التوليد
        self.write_receipt(receipt, out_path)
        receipt.seconds_total = time.perf_counter() - started
        return receipt

    # ------------------------------------------------------------ التوثيق
    def write_receipt(self, receipt: AIReceipt, out_dir: str | Path) -> list[str]:
        """اكتب الإيصال (JSON + MD) داخل ``<out>/.zyko/`` — أعدها بأسمائها."""
        base = Path(out_dir) / ".zyko"
        base.mkdir(parents=True, exist_ok=True)
        written = []
        json_path = base / "ai_receipt.json"
        md_path = base / "AI_RECEIPT.md"
        json_path.write_text(receipt.to_json(), encoding="utf-8")
        md_path.write_text(receipt.to_md(), encoding="utf-8")
        written = [str(json_path), str(md_path)]
        return written
