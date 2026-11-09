"""zyko.ai.receipt — إيصال جلسة الذكاء: سلسلة أدلة موقّعة بالبصمات.

كل خطوة في الجلسة تسجّل: ماذا نُفِّذ، وما رمز خروجه، وما بصمة sha256
لأثره على القرص. الجلسة «مقبولة» فقط إذا اجتازت كل خطواتها بواباتها —
وإيصالها هو الدليل المكتوب، حتمي بالبايت مثل بقية المصنع (بلا أزمنة
إلا عند طلب ``include_timing`` صراحةً، كما في كل وحدات المحرك).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from zyko.version import __version__

SCHEMA = "zyko.ai.receipt/v1"


def hash_text(text: str) -> str:
    """بصمة sha256 لنص — ثابتة عبر المنصات واللغات."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    """بصمة sha256 لملف على القرص — الدليل على أن الأثر لم يُمَسّ."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class StepRecord:
    """سطر واحد في سلسلة الأدلة: خطوة واحدة، حكم واحد، بصماتها."""

    step: str  # "plan" | "generate" | "baseline_update" | "baseline_check"
    title_ar: str
    ok: bool
    exit_code: int
    details_ar: str = ""
    evidence: dict[str, str] = field(default_factory=dict)  # مسار نسبي ⇒ sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "title_ar": self.title_ar,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "details_ar": self.details_ar,
            "evidence": dict(sorted(self.evidence.items())),
        }


@dataclass
class AIReceipt:
    """إيصال جلسة كاملة: الهدف، العقل، الخطوات بالترتيب، والحكم النهائي.

    الحتمية: ``to_dict`` مفاتيحه بترتيب ثابت، والمسار يُخزَّن باسم
    المجلد لا مساره المطلق — إيصالان لهدفين متطابقين متطابقان بالبايت.
    """

    goal: str
    brain: str
    brain_deterministic: bool
    out: str  # اسم مجلد الإخراج فقط (لا مسار مطلق — حفظًا للحتمية)
    rounds: int = 1
    fail_under: int = 75
    dry_run: bool = False
    ok: bool = True
    failed_step: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    plan: dict[str, object] | None = None
    min_score_after: int = 0
    files_written: list[str] = field(default_factory=list)
    seconds_total: float = 0.0

    # ------------------------------------------------------------ البناء
    def add(self, record: StepRecord) -> None:
        """أضف خطوة؛ أول خطوة غير ناجحة تحدد ``failed_step`` وتُسقط الحكم."""
        self.steps.append(record)
        if not record.ok and self.ok:
            self.ok = False
            self.failed_step = record.step

    # ------------------------------------------------------------ المخرجات
    def to_dict(self, *, include_timing: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "zyko_version": __version__,
            "mode": "ai_session",
            "ok": self.ok,
            "goal": self.goal,
            "brain": self.brain,
            "brain_deterministic": self.brain_deterministic,
            "out": self.out,
            "rounds": self.rounds,
            "fail_under": self.fail_under,
            "dry_run": self.dry_run,
            "failed_step": self.failed_step,
            "min_score_after": self.min_score_after,
            "files_written": list(self.files_written),
            "plan": self.plan,
            "steps": [s.to_dict() for s in self.steps],
            "verdict_ar": self.verdict_ar(),
        }
        if include_timing:
            payload["seconds_total"] = round(self.seconds_total, 4)
        return payload

    def to_json(self, *, include_timing: bool = False) -> str:
        """JSON حتمي بالبايت: مفاتيح مرتبة، بلا أزمنة افتراضيًا."""
        return (
            json.dumps(
                self.to_dict(include_timing=include_timing),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def verdict_ar(self) -> str:
        if self.ok:
            return "الجلسة مقبولة — كل البوابات خضراء ✅"
        return f"الجلسة مرفوضة — توقفت عند بوابة «{self.failed_step}» ❌"

    def to_md(self) -> str:
        """إيصال عربي مقروء — نفس الأدلة نفسها بلا أي إضافات."""
        lines: list[str] = ["# إيصال جلسة zyko AI", ""]
        lines.append(f"- الحكم: {self.verdict_ar()}")
        lines.append(f"- الهدف: {self.goal}")
        lines.append(f"- العقل: {self.brain} (حتمي: {'نعم' if self.brain_deterministic else 'لا'})")
        lines.append(f"- مجلد الإخراج: {self.out}")
        mode = "تشغيل جاف — لا كتابة" if self.dry_run else "كتابة فعلية"
        lines.append(f"- النمط: {mode}")
        if self.plan is not None:
            name = self.plan.get("name", "") if isinstance(self.plan, dict) else ""
            template = self.plan.get("template", "") if isinstance(self.plan, dict) else ""
            lines.append(f"- المخطط: {name} (قالب: {template})")
        lines.append("")
        lines.append("## الخطوات (سلسلة الأدلة)")
        lines.append("")
        lines.append("| الخطوة | الحكم | رمز الخروج | الدليل |")
        lines.append("|---|---|---|---|")
        for s in self.steps:
            state = "نجاح" if s.ok else "رفض"
            lines.append(f"| {s.title_ar} | {state} | {s.exit_code} | {s.details_ar} |")
        lines.append("")
        hashed = [(s.step, p, h) for s in self.steps for p, h in sorted(s.evidence.items())]
        if hashed:
            lines.append("## البصمات (sha256)")
            lines.append("")
            for step, path, digest in hashed:
                lines.append(f"- `{path}` — {digest} ({step})")
            lines.append("")
        return "\n".join(lines)
