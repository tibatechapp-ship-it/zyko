"""zyko.benchmarks.repair_loop — عقل الإصلاح الموسع: حلقة تلقيم الفشل داخل العقود (جولة 9).

درس الجولة 8 بالبايت: رقعتان من ست رُفضتا بـ ``git apply`` (رقع مشوهة)
وحل واحد فقط أُصلح — لأن العقل رأى محاولته واحدة بلا رجعية. هذه
الجولة ترفع العقل من «جولة واحدة معلنة النتيجة» إلى **حلقة مقيّدة
الميزانية تُغذّى بفشلها**:

1. **اقتراح** رقعة من العقل (مع رجعية المحاولة السابقة إن وُجدت).
2. **العقد** أولًا: حرس الرقعة نفسه (مسارات نسبية، لا أسرار، لا حذف
   اختبارات، سقف حجم) + سياسة تعدد ملفات معلنة — الرفض بسببه العربي
   لا يخترق أبدًا، ويصير رجعية للمحاولة التالية.
3. **التطبيق** عبر ``git apply`` — وخطأ التطبيق النصي نفسه يتحول
   إلى رجعية للمحاولة التالية.
4. **القياس** بعقد الجولة 8 نفسها: عقد FAIL_TO_PASS وPASS_TO_PASS
   بعد الرقعة — الفاشلة منها تتحول إلى رجعية (أول 12 عقدة مرتبة).
5. **الانصراف عند أول حلّ** أو عند نهاية الميزانية المعلنة — كل محاولة
   في الإيصال، والفشل صادق لا مُجمَّل.

التمدد الموثق على الجولة 8: الرقعة المطلوبة قد تلمس حتى ``max_files``
مسارات، واختيار الملف يعاد كل محاولة فتستطيع الحلقة تغيير الملف نفسه
حين تدل الرجعية على خطأ الاختيار. السلسلة كلها حتمية بالبايت (بصمة
sha256، الأزمنة خارجها) — والشبكة حقن (``Runner``) فتبقى الاختبارات
بلا شبكة إطلاقًا.

    from zyko.benchmarks.repair_loop import RepairLoop

    loop = RepairLoop(choice_brain, diff_brain, max_attempts=3)
    result = loop.run(instance, workdir, python_bin, base_verdict=base)
    result.resolved_env   # حكم الجولة 8 نفسه — مقارنة عادلة
    result.chain_hash     # بصمة الحلقة كاملة
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from zyko.benchmarks.patch_surgeon import apply_tolerant, revert_candidate
from zyko.benchmarks.swebench import (
    DEFAULT_TIMEOUT_S,
    SWEInstance,
    SWEVerdict,
    _sha16,
    build_choice_request,
    build_diff_request,
    check_patch_contract,
    diff_paths,
    extract_diff,
    parse_choice,
    repo_py_tree,
    run_ids,
)

__all__ = [
    "MAX_ATTEMPTS_DEFAULT",
    "MAX_FILES_DEFAULT",
    "PATCH_BUDGET_BYTES",
    "RepairLoop",
    "RepairLoopResult",
    "LoopAttempt",
    "feedback_from_apply_error",
    "feedback_from_contract",
    "feedback_from_failed_tests",
    "feedback_from_regression",
]

# الميزانيات المعلنة — لا سقف خفي ولا نهاية مفتوحة
MAX_ATTEMPTS_DEFAULT = 3
MAX_FILES_DEFAULT = 3
PATCH_BUDGET_BYTES = 64_000

Runner = Callable[..., Any]

_APPLY_FEEDBACK_TITLE_AR = "رجعية التطبيق — رقعتك السابقة رفضها git apply، صحّح الصيغة الموحدة كاملة"
_TESTS_FEEDBACK_TITLE_AR = "رجعية الاختبارات — عقد FAIL_TO_PASS ما زال فاشلاً بعد رقعتك"
_CONTRACT_FEEDBACK_TITLE_AR = "رجعية الحرس — رقعتك خرقت عقداً معلناً"
_REGRESSION_FEEDBACK_TITLE_AR = (
    "رجعية التراجع — رقعتك كسرت عقداً PASS_TO_PASS كانت ناجحة عند الأساس، وأُرجِعت"
)


def feedback_from_apply_error(error_ar: str) -> str:
    """رجعية خطأ التطبيق: نص الخطأ نفسه يذهب للعقل — لا إعادة صمّاء."""
    return f"{_APPLY_FEEDBACK_TITLE_AR}:\n{error_ar}"


def feedback_from_contract(reason_ar: str) -> str:
    """رجعية رفض الحرس: سبب الرفض العربي حرفياً."""
    return f"{_CONTRACT_FEEDBACK_TITLE_AR}:\n{reason_ar}"


def feedback_from_failed_tests(failed_ids: tuple[str, ...]) -> str:
    """رجعية الاختبارات: قائمة العقد الفاشلة بعد رقعتك — مرتبة حتمياً."""
    listed = "\n".join(sorted(failed_ids)[:12]) or "(لا تفاصيل)"
    return f"{_TESTS_FEEDBACK_TITLE_AR}:\n{listed}"


def feedback_from_regression(
    broken_ids: tuple[str, ...], reverted: bool, revert_reason_ar: str = ""
) -> str:
    """رجعية حرس التراجع (الموجة 20): العقد المكسورة + مصير الرقعة حرفياً.

    درس العينة الواسعة: 7 حالات كسرت عقداً ناجحة عند الأساس وبقيت
    الرقعة على الشجرة فتكدّس التراجع في المحاولات التالية. هنا الرقعة
    تُرجَع إلى الأساس والرجعية تصرّح بذلك — العقل يعرف أن شجرته نظيفة
    وأن عليه إصلاح الفشل دون كسر الناجح.
    """
    listed = "\n".join(sorted(broken_ids)[:12]) or "(لا تفاصيل)"
    fate = (
        "الشجرة أُرجِعت إلى الأساس — ابدأ من نظيف ولا تكسر الناجح"
        if reverted
        else f"تعذّر الإرجاع الآلي: {revert_reason_ar or 'سبب غير معروف'}"
    )
    return f"{_REGRESSION_FEEDBACK_TITLE_AR}:\nالعقد المكسورة:\n{listed}\n{fate}"


@dataclass(frozen=True)
class LoopAttempt:
    """محاولة واحدة داخل الحلقة — كل ما جرى بالبايت."""

    index: int  # 1, 2, 3 … — ترتيب معلن
    feedback_sha16: str  # بصمة الرجعية التي بُني عليها الطلب (فارغة للمحاولة الأولى)
    file_choice: str | None
    patch_sha16: str
    accepted: bool  # اجتازت البوابات + الحرس؟
    contract_reason_ar: str
    applied: bool
    apply_error_ar: str | None
    stop_reason_ar: str  # لماذا واصلت أو انصرفت بعد هذه المحاولة
    apply_mode: str = ""  # الموجة 20: كاملة / بالملفات / بالأجزاء — الوضع المعلن
    reverted: bool = False  # الموجة 20: حرس التراجع أرجع الرقعة بعد القياس

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "feedback_sha16": self.feedback_sha16,
            "file_choice": self.file_choice,
            "patch_sha16": self.patch_sha16,
            "accepted": self.accepted,
            "contract_reason_ar": self.contract_reason_ar,
            "applied": self.applied,
            "apply_error_ar": self.apply_error_ar,
            "stop_reason_ar": self.stop_reason_ar,
            "apply_mode": self.apply_mode,
            "reverted": self.reverted,
        }


@dataclass(frozen=True)
class RepairLoopResult:
    """نتيجة الحلقة كاملة — الحكم النهائي من عقد الجولة 8 نفسها."""

    instance_id: str
    attempts: tuple[LoopAttempt, ...]
    verdict: SWEVerdict  # حكم آخر حالة قابلة للحكم (مطبقة وقِيست)
    file_choices: tuple[str | None, ...]
    chain_hash: str = ""
    note_ar: str = ""

    @property
    def resolved_env(self) -> bool:
        return self.verdict.resolved_env

    @property
    def resolved_strict(self) -> bool:
        return self.verdict.resolved_strict

    def to_dict(self) -> dict[str, Any]:
        doc = {
            "instance_id": self.instance_id,
            "attempts": [a.to_dict() for a in self.attempts],
            "verdict": self.verdict.to_dict(),
            "file_choices": list(self.file_choices),
            "note_ar": self.note_ar,
        }
        if self.chain_hash:
            doc["chain_hash"] = self.chain_hash
        return doc


class RepairLoop:
    """حلقة الإصلاح الموسعة — اقتراح ← عقد ← تطبيق ← قياس ← تلقيم الفشل.

    ``choice_brain``/``diff_brain`` مُغلَّفان بـ ``GatedBrain`` مسبقاً —
    والحواجز (PII ثم RTL ثم حرس الرقعة) قبل أي لمس للشجرة أو الصندوق.
    """

    def __init__(
        self,
        choice_brain: Any,
        diff_brain: Any,
        *,
        max_attempts: int = MAX_ATTEMPTS_DEFAULT,
        max_files: int = MAX_FILES_DEFAULT,
        map_lines: tuple[str, ...] | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 8:
            raise ValueError(f"الميزانية خارج العقد (1–8): {max_attempts}")
        if max_files < 1 or max_files > 12:
            raise ValueError(f"سقف الملفات خارج العقد (1–12): {max_files}")
        self.choice_brain = choice_brain
        self.diff_brain = diff_brain
        self.max_attempts = max_attempts
        self.max_files = max_files
        # جولة 11: الخريطة الدلالية تُبنى مرة وتُلحق بكل طلب اختيار
        self.map_lines = map_lines

    # ------------------------------------------------------------- الحرس
    def _check_contract(self, patch: str) -> tuple[bool, str]:
        """حرس الجولة 8 (مسارات/أسرار/حذف اختبارات/سقف) + سياسة تعدد الملفات."""
        allowed, reason = check_patch_contract(patch)
        if not allowed:
            return False, reason
        unique = set(diff_paths(patch))
        if len(unique) > self.max_files:
            return False, (
                f"الرقعة تلمس {len(unique)} مساراً — فوق سياسة تعدد الملفات المعلنة ({self.max_files})"
            )
        return True, "مسموح"

    # ------------------------------------------------------------- الحلقة
    def run(
        self,
        instance: SWEInstance,
        workdir: Any,
        python_bin: str,
        *,
        env_extra: dict[str, str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        runner: Runner = subprocess.run,
        extra_args: tuple[str, ...] = (),
        base_verdict: SWEVerdict | None = None,
    ) -> RepairLoopResult:
        """شغّل الحلقة على حالة واحدة — انصراف عند أول حلّ أو نهاية الميزانية.

        ``base_verdict``: قياس الأساس المحسوب مسبقاً في المتسابق — إن قدم
        فيُستعمل كما هو (لا قياس مزدوج) وحُقائق الأساس تظل في الإيصال.
        """
        tree = repo_py_tree(workdir, runner)
        attempts: list[LoopAttempt] = []
        base_f2p = base_verdict.f2p_failed_at_base if base_verdict else ()
        base_p2p = base_verdict.p2p_failed_at_base if base_verdict else ()
        verdict = SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=False,
            apply_error_ar=None,
            f2p_failed_at_base=tuple(sorted(base_f2p)),
            p2p_failed_at_base=tuple(sorted(base_p2p)),
            f2p_passed_after=(),
            f2p_failed_after=(),
            p2p_failed_after=(),
            runs_error_ar=None,
            attempts_note_ar="لم تُطبَّق أي رقعة في الميزانية",
        )
        choices: list[str | None] = []
        feedback: str | None = None

        if not tree:
            attempts.append(
                LoopAttempt(
                    index=1,
                    feedback_sha16="",
                    file_choice=None,
                    patch_sha16="",
                    accepted=False,
                    contract_reason_ar="لا شجرة مصدر — المستودع غير مهيأ",
                    applied=False,
                    apply_error_ar=None,
                    stop_reason_ar="انصراف — لا شجرة",
                )
            )
            return self._result(instance, attempts, verdict, choices)

        for index in range(1, self.max_attempts + 1):
            last = index == self.max_attempts
            feedback_sha = _sha16(feedback) if feedback else ""
            suffix = f"\n\nرجعية المحاولة السابقة:\n{feedback}" if (feedback and index > 1) else ""

            choice = self.choice_brain.propose(
                build_choice_request(instance, tree, map_lines=self.map_lines) + suffix
            )
            chosen = parse_choice(choice.text, tree) if choice.accepted else None
            choices.append(chosen)
            if chosen is None:
                attempts.append(
                    LoopAttempt(
                        index=index,
                        feedback_sha16=feedback_sha,
                        file_choice=None,
                        patch_sha16="",
                        accepted=False,
                        contract_reason_ar="اختيار الملف رُفض ببوابة أو لم يعطِ مساراً موجوداً",
                        applied=False,
                        apply_error_ar=None,
                        stop_reason_ar="نهاية الميزانية — لا ملف صالح"
                        if last
                        else "انصراف — لا ملف صالح للمحاولة القادمة",
                    )
                )
                break

            content = (workdir / chosen).read_text(encoding="utf-8", errors="replace")
            diff_reply = self.diff_brain.propose(
                build_diff_request(instance, chosen, content) + suffix
            )
            if not diff_reply.accepted:
                attempts.append(
                    LoopAttempt(
                        index=index,
                        feedback_sha16=feedback_sha,
                        file_choice=chosen,
                        patch_sha16="",
                        accepted=False,
                        contract_reason_ar="الرقعة رُفضت ببوابة (PII أو RTL)",
                        applied=False,
                        apply_error_ar=None,
                        stop_reason_ar="نهاية الميزانية — البوابات رفضت"
                        if last
                        else "انصراف — البوابات رفضت اقتراحاً بلا رجعية ممكنة",
                    )
                )
                break

            patch = extract_diff(diff_reply.text, fallback_path=chosen)
            if patch is None:
                feedback = feedback_from_apply_error(
                    "لا رقعة موحدة في الرد — أعد الرقعة في كتلة ```diff كاملة الأجزاء"
                )
                attempts.append(
                    LoopAttempt(
                        index=index,
                        feedback_sha16=feedback_sha,
                        file_choice=chosen,
                        patch_sha16="",
                        accepted=True,
                        contract_reason_ar="لا رقعة موحدة في الرد",
                        applied=False,
                        apply_error_ar=None,
                        stop_reason_ar="نهاية الميزانية — لا رقعة"
                        if last
                        else "متابعة — رجعية الصيغة بُنيت",
                    )
                )
                continue

            allowed, reason = self._check_contract(patch)
            if not allowed:
                feedback = feedback_from_contract(reason)
                attempts.append(
                    LoopAttempt(
                        index=index,
                        feedback_sha16=feedback_sha,
                        file_choice=chosen,
                        patch_sha16=_sha16(patch),
                        accepted=False,
                        contract_reason_ar=reason,
                        applied=False,
                        apply_error_ar=None,
                        stop_reason_ar="نهاية الميزانية — الحرس رفض"
                        if last
                        else "متابعة — رجعية الحرس بُنيت",
                    )
                )
                continue

            # الموجة 20: سلّم التطبيق المعلن — فحص صياغي محلي ثم كاملة ←
            # بالملفات ← بالأجزاء؛ الوضع الجزئي موثق بالأجزاء لا مطموس،
            # والفشل الكلي يحمل سبب git وأخطاء الصياغة معاً في رجعية واحدة
            tol = apply_tolerant(workdir, patch, runner)
            applied = tol.applied
            apply_reason: str | None = None if applied else tol.reason_ar
            if not applied and tol.syntax_errors:
                apply_reason = (
                    "فشل الفحص الصياغي: "
                    + " | ".join(tol.syntax_errors)[:400]
                    + " — "
                    + (tol.reason_ar or "")
                ).rstrip(" —")
            if not applied:
                feedback = feedback_from_apply_error(apply_reason)
                attempts.append(
                    LoopAttempt(
                        index=index,
                        feedback_sha16=feedback_sha,
                        file_choice=chosen,
                        patch_sha16=_sha16(patch),
                        accepted=True,
                        contract_reason_ar=reason,
                        applied=False,
                        apply_error_ar=apply_reason,
                        stop_reason_ar="نهاية الميزانية — التطبيق فشل"
                        if last
                        else "متابعة — رجعية التطبيق بُنيت",
                        apply_mode=tol.mode_ar,
                    )
                )
                continue

            # الرقعة مطبقة — قياس بعد مباشر بعقد الجولة 8 (لا تطبيق ثانوي)
            all_ids = tuple(sorted(set(instance.fail_to_pass) | set(instance.pass_to_pass)))
            after = run_ids(
                workdir,
                all_ids,
                python_bin,
                env_extra=env_extra,
                timeout_s=timeout_s,
                runner=runner,
                extra_args=extra_args,
            )
            f2p_after_failed = frozenset(
                f for f in after.failed_ids if f in set(instance.fail_to_pass)
            )
            p2p_after_failed = frozenset(
                f for f in after.failed_ids if f in set(instance.pass_to_pass)
            )
            verdict = SWEVerdict(
                instance_id=instance.instance_id,
                patch_applied=True,
                apply_error_ar=None,
                f2p_failed_at_base=tuple(sorted(base_f2p)),
                p2p_failed_at_base=tuple(sorted(base_p2p)),
                f2p_passed_after=tuple(sorted(set(instance.fail_to_pass) - f2p_after_failed)),
                f2p_failed_after=tuple(sorted(f2p_after_failed)),
                p2p_failed_after=tuple(sorted(p2p_after_failed)),
                runs_error_ar=after.error_ar,
                patch_sha16=_sha16(patch),
                contract_reason_ar=reason,
                attempts_note_ar=f"الحلقة طبّقت عند المحاولة {index}",
            )
            # الموجة 20: حرس التراجع — رقعة كسرت عقداً ناجحة عند الأساس
            # تُرجَع عكسياً إلى الأساس قبل المحاولة التالية، ورجعيتها تصرّح
            # بالمكسور ومصير الشجرة. درس multiplan «الصفقة تُرجع بالبايت»
            # وصل للحلقة العامة: لا تراكم تراجع على شجرة مكسورة.
            new_regressions = tuple(sorted(set(p2p_after_failed) - set(base_p2p)))
            resolved = verdict.resolved_env or verdict.resolved_strict
            reverted = False
            revert_reason_ar = ""
            if new_regressions and not resolved and not verdict.runs_error_ar:
                reverted, revert_reason_ar = revert_candidate(
                    workdir, patch, runner, tol.applied_subpatches
                )
            attempts.append(
                LoopAttempt(
                    index=index,
                    feedback_sha16=feedback_sha,
                    file_choice=chosen,
                    patch_sha16=_sha16(patch),
                    accepted=True,
                    contract_reason_ar=reason,
                    applied=True,
                    apply_error_ar=None,
                    stop_reason_ar=(
                        "انصراف — حلّ"
                        if resolved
                        else "متابعة — حرس التراجع أرجع الرقعة وبنى رجعيتها"
                        if new_regressions
                        else "متابعة — رجعية الاختبارات بُنيت"
                    ),
                    apply_mode=tol.mode_ar,
                    reverted=reverted,
                )
            )

            if resolved:
                break
            if verdict.runs_error_ar:
                break
            if last:
                break
            if new_regressions:
                feedback = feedback_from_regression(new_regressions, reverted, revert_reason_ar)
            else:
                feedback = feedback_from_failed_tests(
                    verdict.f2p_failed_after or tuple(after.failed_ids)
                )

        return self._result(instance, attempts, verdict, choices)

    # ------------------------------------------------------------- الإيصال
    def _result(
        self,
        instance: SWEInstance,
        attempts: list[LoopAttempt],
        verdict: SWEVerdict,
        choices: list[str | None],
    ) -> RepairLoopResult:
        payload = {
            "instance_id": instance.instance_id,
            "attempts": [a.to_dict() for a in attempts],
            "verdict": verdict.to_dict(),
        }
        chain = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return RepairLoopResult(
            instance_id=instance.instance_id,
            attempts=tuple(attempts),
            verdict=verdict,
            file_choices=tuple(choices),
            chain_hash=chain,
        )
