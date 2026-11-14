"""verify.py — التحقق الذاتي (بنية 3 من النظام الهجين).

العقد: **لا ثقة أبداً بإصلاح محرك تفكير**. كل إصلاح مقترح يعيد المرور
على البوابة الثابتة كاملة: هل المصدر المصلح يُحلَّل؟ هل ظهرت ملاحظات
جديدة لم تكن في الأصل؟ هل الدرجة لم تتراجع؟ وهل عالج القاعدة المقصودة
فعلاً (عدد إصاباتها انخفض)؟ ما يفشل بنداً واحداً يُرفض بأسباب عربية
مسماة — الرفض معلن لا تخمين.

العدّ بالقاعدة لا بالسطر: الإصلاح ينقل الأسطر بشكل مشروع، فالمرجع
هو عدد إصابات كل rule_id قبل وبعد — حتمي بالبايت.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from zyko.reviewer.engine import ReviewEngine, ReviewResult

__all__ = ["FixVerdict", "FixVerifier"]


@dataclass
class FixVerdict:
    """حكم إصلاح: مقبول/مرفوض + الفحوص الأربعة + الأسباب + بصمة المصدر."""

    accepted: bool
    checks: dict
    score_before: int
    score_after: int
    reasons_ar: tuple[str, ...]
    fixed_sha16: str

    def to_dict(self) -> dict:
        return {
            "schema": "zyko.hybrid.fix_verdict/1",
            "accepted": self.accepted,
            "checks": dict(self.checks),
            "score_before": self.score_before,
            "score_after": self.score_after,
            "reasons_ar": list(self.reasons_ar),
            "fixed_sha16": self.fixed_sha16,
        }


def _rule_counts(result: ReviewResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in result.findings:
        counts[f.rule_id] = counts.get(f.rule_id, 0) + 1
    return counts


class FixVerifier:
    """بوابة ثابتة على كل إصلاح مقترح — المحرك يقترح والبوابة تحكم."""

    def __init__(self, engine: ReviewEngine | None = None) -> None:
        self._engine = engine or ReviewEngine()

    def verify(
        self,
        original_source: str,
        fixed_source: str,
        *,
        filename: str = "<text>",
        target_rule_id: str | None = None,
    ) -> FixVerdict:
        original = self._engine.review_source(original_source, filename)
        reasons: list[str] = []

        parses = True
        fixed = self._engine.review_source(fixed_source, filename)
        if fixed.parse_error is not None:
            parses = False
            reasons.append("المصدر المصلح لا يُحلَّل — رفض بنيوي")

        before_counts = _rule_counts(original)
        after_counts = _rule_counts(fixed)

        new_rules = sorted(set(after_counts) - set(before_counts))
        no_new = not new_rules
        if new_rules:
            reasons.append(f"ملاحظات جديدة ظهرت بعد الإصلاح: {', '.join(new_rules)}")

        score_not_worse = fixed.score >= original.score
        if not score_not_worse:
            reasons.append(f"الدرجة تراجعت من {original.score} إلى {fixed.score}")

        if target_rule_id is not None:
            addressed = after_counts.get(target_rule_id, 0) < before_counts.get(target_rule_id, 0)
            if not addressed:
                reasons.append(f"القاعدة المقصودة {target_rule_id} لم تنقص إصاباتها")
        else:
            addressed = True

        accepted = parses and no_new and score_not_worse and addressed
        return FixVerdict(
            accepted=accepted,
            checks={
                "parses": parses,
                "no_new_findings": no_new,
                "score_not_worse": score_not_worse,
                "target_addressed": addressed,
            },
            score_before=original.score,
            score_after=fixed.score,
            reasons_ar=tuple(reasons),
            fixed_sha16=hashlib.sha256(fixed_source.encode()).hexdigest()[:16],
        )
