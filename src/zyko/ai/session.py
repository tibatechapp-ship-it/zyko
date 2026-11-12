"""zyko.ai.session — جلسة الذكاء الموثّقة: هدف عربي ⇒ مشروع عبر البوابات.

الجلسة هي «التجميع» الأول لـ zyko AI فوق المصنع، وكل نداء فيها يمرّ
على بوابة المصنع القابلة للتحقق، بنمطين متعارف عليهما:

* ``factory`` (افتراضي): هدف عربي ⇒ مشروع جديد عبر محرك الحلقة:

  1) «خطة» — عقل مقيّد بالبوابات يقترح خطة (المخطط الحتمي افتراضيًا)؛
     اقتراح فيه بيان شخصي أو خطأ اتجاه ⇒ رفض فوري وقف قبل أي توليد.
  2) «توليد» — تفويض حرفي لمحرك الحلقة ``PipelineEngine`` (نفس المراجعة
     والإصلاح ونفس الدرجات)، مع حد قبول ``fail_under``.
  3) «خط أساس» — تفويض حرفي لـ ``BaselineEngine``: تسجيل ثم فحص؛ أي
     تراجع ⇒ رفض.

* ``existing``: هدف عربي يحمل مسار ملف قائم ⇒ نفس عقل ``zyko do``
  (``classify → route → run``) خلف بوابة الجلسة نفسها:

  1) «خطة» — البوابات نفسها (PII ← RTL) على اقتراح العقل.
  2) «تنفيذ حتمي» — خطة orchestrator تُنفّذ على الملف الحقيقي عبر
     المحرّس والإيصال الموحّد الموقّع؛ الكتابة الفعلية (إصلاح الملف في
     مكانه) عقد ``zyko do --write`` نفسه، والتجريبي لا يكتب شيئاً.
  3) حد القبول ``fail_under`` يُفحص على درجة الملف بعد الإصلاح في وضع
     الكتابة فقط — التشغيل الجاف يوثّق الدرجة الحالية بصدق دون إنكار
     الجلسة (فعله التشخيص لا التطبيق).
  4) «خط أساس» — تُوثَّق كتخطٍّ صريح: الكود القائم خارج خط أساس المصنع.

* كل خطوة تُوثَّق في الإيصال ببصماتها — لا تجاوز ولا استثناء خارج.

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
SESSION_MODES: tuple[str, ...] = ("factory", "existing")
EXISTING_GATE_TITLE = "بوابة التنفيذ الحتمي (orchestrator على الكود القائم)"
MODE_GATE_TITLE = "بوابة اكتشاف النمط (حتمية من الهدف والقرص)"


def detect_session_mode(desc: str, out_dir: str | Path) -> tuple[str, str]:
    """اكتشاف نمط الجلسة آليًا — حتمي من الهدف والقرص (جولة 10).

    العلة الحية التي وجدها التدقيق: النمط كان يتطلب علمًا صريحًا دائمًا
    (``factory`` الافتراضي)، وهدف «راجع وأصلح ملفًا قائمًا» على مشروع
    حقيقي كان يذهب للمصنع — أو يُحجب بحرس مجلد الإخراج المفروض على
    المصنع. العقد هنا:

    1. المستخرج الحتمي نفسه الذي يعمل في ``zyko do`` (``extract_context``)
       يستخرج المسار من الهدف — مسار ملف **موجود على القرص** ⇒
       ``existing`` (نية واضحة: كود قائم).
    2. لا مسار، أو مسار غير موجود ⇒ ``factory`` — لا تخمين على غياب.
    3. علم المتصل الصريح يغلب الكشف دائمًا (يبقى ``AISession(mode=…)``
       كما هو) — الكشف يملأ الفراغ لا أنهي العقد.

    يعيد ``(النمط، السبب_العربي)`` — السبب يدخل الإيصال فيصير القرار
    جزءًا من سلسلة الأدلة لا حدسًا صامتًا.
    """
    from zyko.orchestrator import extract_context

    context = extract_context(desc)
    target = str(context.get("path") or "").strip()
    if target:
        if Path(target).is_file():
            return "existing", (
                f"الهدف يحدد ملفاً قائماً على القرص ({target}) — النمط existing بقرار حتمي"
            )
        return "factory", (
            f"الهدف يذكر مساراً غير موجود على القرص ({target}) — النمط factory بقرار حتمي"
        )
    return "factory", "الهدف لا يحدد ملفاً قائماً — النمط factory الافتراضي بقرار حتمي"


class AISession:
    """منسّق جلسة واحدة: عقل + بوابات + عمل (توليد أو كود قائم) + حارس."""

    def __init__(
        self,
        brain: Brain | None = None,
        *,
        rounds: int = 1,
        fail_under: int = DEFAULT_FAIL_UNDER,
        mode: str | None = None,
    ) -> None:
        # ``None`` = اكتشاف آلي عند التشغيل (جولة 10) — الصريح يغلب الكشف دائمًا
        if mode is not None and mode not in SESSION_MODES:
            raise ValueError(
                f"نمط جلسة غير معروف: {mode!r} — الأنماط المعروفة: {'، '.join(SESSION_MODES)}"
            )
        self.brain: Brain = brain if brain is not None else GatedBrain(PlannerBrain())
        self.rounds = rounds
        self.fail_under = fail_under
        self.mode = mode

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
        # ---- 0ب) بوابة اكتشاف النمط: حتمية من الهدف والقرص — الصريح يغلب
        if self.mode is not None:
            mode, mode_reason = self.mode, f"النمط صريح من المتصل ({self.mode}) — الكشف لا يعمل"
        else:
            mode, mode_reason = detect_session_mode(desc, out_path)
        receipt.add(
            StepRecord(
                step="mode",
                title_ar=MODE_GATE_TITLE,
                ok=True,
                exit_code=0,
                details_ar=mode_reason,
            )
        )

        # ---- 0ج) حرس مجلد الإخراج — على المصنع فقط: مجلد المشروع القائم
        # هو مكان العمل نفسه في النمط existing (العلة الحية وجدها التدقيق:
        # الحرس كان يحجب كل مشروع حقيقي غير فارغ في وضع الكتابة)
        if mode == "factory" and write and out_path.exists() and any(out_path.iterdir()):
            return self._structural_block(
                receipt,
                "out",
                "حرس المدخلات",
                f"مجلد الإخراج «{out_path.name}» موجود وغير فارغ — اكتب مجلدًا جديدًا فارغًا",
            )

        # ---- 1) بوابة الخطة: اقتراح العقل لا يمر إلا عبر PII ثم RTL
        proposal = self.brain.propose(desc)
        if not proposal.accepted:
            # كل الأحكام الفاشلة تُوثَّق — قصة الرفض كاملة لا أول فشل فقط
            evidence = "؛ ".join(
                v.details_ar for v in proposal.verdicts if not v.passed and v.details_ar
            )
            receipt.add(
                StepRecord(
                    step="plan",
                    title_ar="بوابة الخطة (عقل ← PII ← RTL)",
                    ok=False,
                    exit_code=1,
                    details_ar=evidence or "اقتراح مرفوض",
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

        # ---- 2) بوابة العمل: مصنع مشاريع (factory) أو تنفيذ على كود قائم (existing)
        if mode == "existing":
            return self._run_existing(receipt, desc, out_path, write=write, started=started)

        # ---- 2ب) بوابة التوليد: تفويض حرفي لمحرك الحلقة (بلا إعادة تنفيذ)
        result = PipelineEngine().run(
            desc, out_path, git_init=False, rounds=self.rounds, write=write
        )
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
        # الإثبات يغطي كل ملفات المشروع المولَّد على القرص (وليس ما أصلحه
        # المحرّك فقط) — القوالب المثالية لا تحتاج إصلاحًا فتبقى الإثباتات كاملة.
        evidence = {
            rel: hash_file(out_path / rel)
            for rel in sorted(set(result.files) | set(result.written))
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
                details_ar=update.verdict_ar
                or ("؛ ".join(update.problems) if update.problems else "تسجيل خط الأساس"),
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

    # ------------------------------------------------------------ الوضع القائم
    def _run_existing(
        self,
        receipt: AIReceipt,
        desc: str,
        out_path: Path,
        *,
        write: bool,
        started: float,
    ) -> AIReceipt:
        """نمط ``existing``: عقل ``zyko do`` كاملاً (classify → route → run)
        على ملف قائم حقيقي، خلف بوابة الجلسة نفسها وبإيصالها الموثّق.

        العقد: الكتابة الفعلية تُصلح الملف في مكانه (عقد ``zyko do --write``
        نفسه)، والتجريبي لا يلمس القرص؛ حد ``fail_under`` يُفحص على درجة
        الملف بعد الإصلاح في وضع الكتابة فقط؛ بوابات خط الأساس تُوثَّق
        كتخطٍّ صريح (الكود القائم خارج خط أساس المصنع)."""
        from zyko.orchestrator import classify, extract_context, route
        from zyko.orchestrator.run import run as orchestrator_run
        from zyko.orchestrator.run import step_summary_ar

        classification = classify(desc)
        context = extract_context(desc)
        plan = route(classification, context=context)
        target = context.get("path") or ""
        target_path = Path(target) if target else None
        if target_path is None or not target_path.is_file():
            receipt.add(
                StepRecord(
                    step="orchestrator",
                    title_ar=EXISTING_GATE_TITLE,
                    ok=False,
                    exit_code=1,
                    details_ar=(
                        "لم يُعثر على ملف قائم في الهدف — المستخرج الحتمي أعاد "
                        f"«{target or 'لا مسار'}» وهو غير موجود على القرص؛ حدّد ملفاً "
                        "قائماً أو استخدم النمط الافتراضي factory لتوليد مشروع جديد"
                    ),
                )
            )
            receipt.seconds_total = time.perf_counter() - started
            return receipt

        sha_before = hash_file(target_path)
        result = orchestrator_run(plan, dry_run=not write)

        parts: list[str] = [
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

        gate_ok = bool(result.steps) and result.ok
        evidence: dict[str, str] = {target: sha_before}

        if write:
            from zyko.reviewer.engine import ReviewEngine

            after = ReviewEngine().review_file(target)
            receipt.min_score_after = after.score
            sha_after = hash_file(target_path)
            if sha_after != sha_before:
                receipt.files_written = [target]
                evidence[target] = sha_after
                parts.append(f"البصمة تغيّرت بعد الإصلاح ({sha_before[:12]}… ← {sha_after[:12]}…)")
            if result.ok and after.score >= self.fail_under:
                parts.append(f"الدرجة بعد الإصلاح {after.score} ≥ الحد {self.fail_under}")
            else:
                gate_ok = False
                if not result.ok:
                    parts.append("توقفت الخطة عند أول فشل موثق")
                else:
                    remaining = sum(after.counts.values())
                    parts.append(
                        f"الدرجة بعد الإصلاح {after.score} دون الحد {self.fail_under}"
                        f" — تبقى {remaining} ملاحظة"
                    )
        else:
            score_now = next(
                (
                    s.output.get("score")
                    for s in result.steps
                    if s.ok and isinstance(s.output, dict) and "score" in s.output
                ),
                None,
            )
            if score_now is not None:
                parts.append(
                    f"الدرجة الحالية {score_now} — تشغيل جاف لم يكتب شيئاً؛"
                    f" الحد {self.fail_under} يُفحص في وضع الكتابة بعد الإصلاح"
                )

        receipt.add(
            StepRecord(
                step="orchestrator",
                title_ar=EXISTING_GATE_TITLE,
                ok=gate_ok,
                exit_code=0 if gate_ok else (2 if not result.ok else 1),
                details_ar="؛ ".join(parts),
                evidence=evidence,
            )
        )

        # بوابات خط الأساس: تخطٍّ موثق — الكود القائم خارج خط أساس المصنع.
        receipt.add(
            StepRecord(
                step="baseline_update",
                title_ar="بوابة خط الأساس — تسجيل",
                ok=True,
                exit_code=0,
                details_ar="تخطٍّ — الكود القائم خارج خط أساس المصنع",
            )
        )
        receipt.add(
            StepRecord(
                step="baseline_check",
                title_ar="بوابة خط الأساس — فحص",
                ok=True,
                exit_code=0,
                details_ar="تخطٍّ — الكود القائم خارج خط أساس المصنع",
            )
        )

        if write:
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
