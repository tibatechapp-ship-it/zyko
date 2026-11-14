"""reasoning.py — واجهة التفكير المجردة والتوجيه الذكي (بنيتا 2 و4).

العقد المجرد: أي محرك تفكير خارجي يجيب أسئلة محددة فقط — لا يُنسخ كود
محرك، بل يُبنى الجسر: المحرك محقون كدالة نداء (caller) والواجهة تحمّل
السياق المنظم وتعيد جواباً موثقاً بالشكل. كل جواب: سؤال + حكم من ثلاثة
(نعم/لا/غير محسوم) + ثقة + إصلاح مقترح + تبرير + اسم المحرك.

التوجيه الذكي (بنية 4) يعيش هنا: الملف النظيف (درجة 100 بلا ملاحظات)
لا يلمس المحرك أبداً، وفئة quality ميكانيكية تبقى ثابتة خالصة —
المحرك يُستدعى للأمني (is_vulnerability) والمنطقي (minimal_fix) فقط.

المحرك الثابت `StaticReasoningEngine`: بديل حتمي بلا شبكة يجيب من
السياق نفسه — للعمل دون اتصال وللاختبارات ولقياس وفر الموارد.
`RemoteReasoningEngine`: جسر لأي محرك خارجي عبر دالة محقونة — فشل
المحرك الخارجي ينحدر حتمياً إلى «غير محسوم» لا انهيار.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = [
    "QUESTIONS",
    "HybridReport",
    "HybridReviewer",
    "ReasoningAnswer",
    "ReasoningEngine",
    "RemoteReasoningEngine",
    "StaticReasoningEngine",
    "route_file",
    "select_findings",
]

# الأسئلة المعتمدة في العقد — المحرك لا يجيب غيرها
QUESTIONS = ("is_vulnerability", "minimal_fix")

_VERDICTS = ("yes", "no", "uncertain")

_QUESTION_AR = {
    "is_vulnerability": "هل هذا التدفق يشكل ثغرة فعلية؟",
    "minimal_fix": "كيف يُصلَح هذا بأقل تأثير؟",
}


@dataclass
class ReasoningAnswer:
    """جواب موثق: سؤال + حكم + ثقة + إصلاح + تبرير + محرك."""

    question: str
    verdict: str
    confidence: float
    fix_ar: str | None
    rationale_ar: str
    engine: str

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "question_ar": _QUESTION_AR.get(self.question, self.question),
            "verdict": self.verdict,
            "confidence": round(self.confidence, 2),
            "fix_ar": self.fix_ar,
            "rationale_ar": self.rationale_ar,
            "engine": self.engine,
        }


class ReasoningEngine(ABC):
    """العقد المجرد: محرك يُسمّى ويجيب أسئلة العقد لا غيرها."""

    name: str = "abstract"

    @abstractmethod
    def ask(self, context: dict, question: str) -> ReasoningAnswer:
        """يجيب سؤالاً معتمداً عن سياق منظم واحد — بلا آثار جانبية."""


class StaticReasoningEngine(ReasoningEngine):
    """محرك حتمي بلا شبكة يجيب من السياق المنظم نفسه — المرجع للقياس."""

    name = "zyko-static"

    def ask(self, context: dict, question: str) -> ReasoningAnswer:
        if question not in QUESTIONS:
            return ReasoningAnswer(question, "uncertain", 0.0, None, "سؤال خارج العقد", self.name)
        finding = context.get("finding", {})
        flow = context.get("flow", {})
        category = finding.get("category", "")
        tainted = bool(flow.get("tainted"))
        suggestion = finding.get("suggestion_ar")
        if question == "is_vulnerability":
            if category == "security" and tainted:
                return ReasoningAnswer(
                    question,
                    "yes",
                    0.8,
                    suggestion,
                    "تدفق ملوث بمصدر معروف وقاعدة أمنية أطلقت — قرينة قوية",
                    self.name,
                )
            if category == "security":
                return ReasoningAnswer(
                    question,
                    "uncertain",
                    0.5,
                    suggestion,
                    "قاعدة أمنية بلا تلويث موثق — تحتاج عيناً بشرية أو محركاً أعمق",
                    self.name,
                )
            return ReasoningAnswer(
                question,
                "no",
                0.9,
                None,
                "قاعدة غير أمنية لا تدل على ثغرة تدفق",
                self.name,
            )
        # minimal_fix
        return ReasoningAnswer(
            question,
            "uncertain",
            0.6,
            suggestion,
            "أقل إصلاح معلن من قاعدة المراجع الثابتة — يمر عبر البوابة الثابتة",
            self.name,
        )


class RemoteReasoningEngine(ReasoningEngine):
    """جسر لأي محرك خارجي: دالة نداء محقونة (سياق + سؤال ⇒ قاموس).

    لا كود محرك هنا إطلاقاً — الواجهة تحمّل وتصادق على الشكل فقط:
    verdict من الثلاثة، confidence 0..1، والباقي نصوص اختيارية. أي فشل
    (شكل غريب، استثناء) ينحدر حتمياً إلى جواب «غير محسوم» موثق.
    """

    def __init__(self, caller, *, name: str) -> None:
        self._caller = caller
        self.name = f"remote:{name}"

    def ask(self, context: dict, question: str) -> ReasoningAnswer:
        try:
            raw = self._caller(context, question)
            if not isinstance(raw, dict):
                raise TypeError("الجواب ليس قاموساً")
            verdict = raw.get("verdict")
            if verdict not in _VERDICTS:
                verdict = "uncertain"
            try:
                confidence = float(raw.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = min(1.0, max(0.0, confidence))
            fix = raw.get("fix_ar")
            rationale = str(raw.get("rationale_ar", ""))
            return ReasoningAnswer(question, verdict, confidence, fix, rationale, self.name)
        except Exception as exc:  # الانحدار الموثق — لا انهيار خط الأنابيب
            return ReasoningAnswer(
                question,
                "uncertain",
                0.0,
                None,
                f"فشل المحرك الخارجي: {type(exc).__name__}",
                self.name,
            )


# --------------------------- بنية 4: التوجيه الذكي ---------------------------


def route_file(result) -> bool:
    """هل يستحق الملف لمس محرك التفكير؟ درجة دون 100 أو ملاحظة أمنية."""
    return result.score < 100 or any(f.category == "security" for f in result.findings)


def select_findings(result) -> tuple:
    """الملاحظات المؤهلة للتفكير: الأمنية والمنطقية — quality ميكانيكية تبقى ثابتة."""
    return tuple(f for f in result.findings if f.category in ("security", "error_handling"))


# --------------------- تقرير المراجعة الهجين (الموزّع) ---------------------


@dataclass
class HybridReport:
    """تقرير موحد: ثابت + تفكير موجَّه + وفر الموارد + إيصال sha16."""

    filename: str
    route_ar: str
    static: dict
    answers: tuple[ReasoningAnswer, ...] = ()
    savings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "schema": "zyko.hybrid.report/1",
            "filename": self.filename,
            "route_ar": self.route_ar,
            "static": self.static,
            "reasoning": [a.to_dict() for a in self.answers],
            "savings": self.savings,
        }
        payload["report_sha16"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:16]
        return payload


# ------------------------- الموزّع: الخط الكامل -------------------------


class HybridReviewer:
    """ثابت أولاً، ثم تفكير موجَّه بالعقد، وكل جواب في تقرير موقّع."""

    def __init__(self, engine: ReasoningEngine | None = None) -> None:
        self._engine = engine

    def review_source(self, source: str, filename: str = "<text>") -> HybridReport:
        from zyko.reviewer.engine import ReviewEngine
        from zyko.reviewer.hybrid.context import build_contexts

        static_result = ReviewEngine().review_source(source, filename)
        findings = select_findings(static_result)
        total = len(static_result.findings)

        if self._engine is None:
            route_ar = "ثابت خالص — المحرك غير مهيأ (الوضع المعلن)"
            answers: tuple[ReasoningAnswer, ...] = ()
            routed = 0
        elif not route_file(static_result):
            route_ar = "ثابت خالص — الملف نظيف (درجة 100 بلا ملاحظات)"
            answers = ()
            routed = 0
        elif not findings:
            route_ar = "ثابت خالص — الملاحظات كلها ميكانيكية (quality)"
            answers = ()
            routed = 0
        else:
            route_ar = "هجين — ملاحظات أمنية/منطقية مرفوعة لمحرك التفكير"
            ctxs = build_contexts(source, filename, static_result)
            by_key = {(c.rule_id, c.line): c for c in ctxs}
            picked: list[ReasoningAnswer] = []
            for f in findings:
                ctx = by_key.get((f.rule_id, f.line))
                if ctx is None:
                    continue
                question = "is_vulnerability" if f.category == "security" else "minimal_fix"
                picked.append(self._engine.ask(ctx.to_dict(), question))
            answers = tuple(picked)
            routed = len(answers)

        savings = {
            "findings_total": total,
            "findings_routed": routed,
            "findings_static_only": total - routed,
            "engine_skipped": self._engine is None or not route_file(static_result),
        }
        return HybridReport(
            filename=filename,
            route_ar=route_ar,
            static=static_result.to_dict(),
            answers=answers,
            savings=savings,
        )
