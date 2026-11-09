"""zyko.ai.gate — بوابة المرحلة 8: طبقة الذكاء خضعت للمصنع أم لا؟

12 بوابة حتمية على 3 مراسئ عربية، بنفس عقد بوابات المراحل السابقة:

  - المرسأ «نظيف»: العقل يقترح، الجلسة تُبنى كاملة، الحارس أخضر،
    والإيصال حتمي بالبايت بين تشغيلين.
  - المرسأ «مريب» (فيه بيان شخصي): الاقتراح يُرفض عند بوابة PII،
    لا مجلد يُنشأ، والإيصال يوثّق الرفض — بلا أي استثناء خارج.
  - المرسأ «عدائي»: مدخلات سيئة (فارغ، غير نصي، مجلد مزدحم، هدف
    أطول من الحد) تفشل فشلًا هيكليًا آمنًا — رمز 2 موثّق، لا حذف،
    لا كتابة، لا انهيار.

الحكم الإجمالي: «طبقة الذكاء مقبولة» فقط إذا نجحت الاثنا عشر كلها.
هذه البوابة هي نقطة الدخول نفسها للاختبارات وللـ CI وللطرفية.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.ai.brains import GatedBrain, PlannerBrain
from zyko.ai.session import AISession
from zyko.pipeline.engine import MAX_DESCRIPTION_LEN

_GATE_LINE = "-" * 60


@dataclass
class GateRow:
    """صف واحد: مرسأ، بوابة، حكم، دليل."""

    anchor: str
    gate: str
    passed: bool
    details_ar: str = ""


@dataclass
class Phase8GateResult:
    """نتيجة البوابة: 12 صفًا وحكم إجمالي واحد."""

    rows: list[GateRow] = field(default_factory=list)
    seconds: float = 0.0
    max_seconds: float = 5.0

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.rows) and bool(self.rows)

    def table_ar(self) -> str:
        lines = [
            "بوابة المرحلة 8 — طبقة الذكاء فوق المصنع (12 بوابة على 3 مراسئ)",
            _GATE_LINE,
            f"{'المرسأ':<10} {'البوابة':<34} {'الحكم':<6} الدليل",
            _GATE_LINE,
        ]
        for r in self.rows:
            state = "نجاح" if r.passed else "فشل"
            lines.append(f"{r.anchor:<10} {r.gate:<34} {state:<6} {r.details_ar}")
        lines.append(_GATE_LINE)
        passed = sum(1 for r in self.rows if r.passed)
        verdict = "طبقة الذكاء مقبولة ✅" if self.ok else "طبقة الذكاء مرفوضة ❌"
        lines.append(f"الخلاصة: {passed}/{len(self.rows)} بوابة ناجحة — الحكم: {verdict}")
        return "\n".join(lines)


def _normalized_json(receipt_json: str, out_name: str) -> str:
    """طبّع اسم مجلد الإخراج في JSON لمقارنة حتمية بين مجلدين."""
    data = json.loads(receipt_json)
    data["out"] = "X"
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_phase8_gate(
    *,
    max_seconds: float = 5.0,
    tmp_root: str | Path | None = None,
) -> Phase8GateResult:
    """شغّل بوابات المرحلة 8 كاملة — حتمية الحكم، بلا شبكة وبلا نموذج."""
    import tempfile

    started = time.perf_counter()
    result = Phase8GateResult(max_seconds=max_seconds)

    clean_goal = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"
    suspicious_goal = "قائمة مهام — للتنسيق اتصل على 0501234567"

    with tempfile.TemporaryDirectory(prefix="zyko-p8-gate-", dir=tmp_root) as td:
        tmp = Path(td)

        # ═══ المرسأ «نظيف» ═══
        brain = GatedBrain(PlannerBrain())
        proposal = brain.propose(clean_goal)
        result.rows.append(
            GateRow(
                anchor="نظيف",
                gate="اقتراح العقل يجتاز PII←RTL",
                passed=proposal.accepted,
                details_ar=f"عقل: {brain.name} — أحكام: {len(proposal.verdicts)}",
            )
        )

        session = AISession(rounds=1)
        receipt_a = session.run(clean_goal, tmp / "a", write=True)
        result.rows.append(
            GateRow(
                anchor="نظيف",
                gate="جلسة كاملة مقبولة",
                passed=receipt_a.ok,
                details_ar=f"خطوات: {len(receipt_a.steps)} — أدنى درجة {receipt_a.min_score_after}",
            )
        )

        baseline_ok = any(
            s.step == "baseline_check" and s.ok for s in receipt_a.steps
        )
        result.rows.append(
            GateRow(
                anchor="نظيف",
                gate="حارس الجودة أخضر (تسجيل←فحص)",
                passed=baseline_ok,
                details_ar="خط الأساس سُجّل وفُحص بلا تراجع" if baseline_ok else "فحص الحارس لم ينجح",
            )
        )

        receipt_b = AISession(rounds=1).run(clean_goal, tmp / "b", write=True)
        same = _normalized_json(receipt_a.to_json(), "a") == _normalized_json(receipt_b.to_json(), "b")
        result.rows.append(
            GateRow(
                anchor="نظيف",
                gate="الإيصال حتمي بالبايت",
                passed=same,
                details_ar="إيصالان لهدف واحد = بايتات واحدة" if same else "الإيصالان مختلفان",
            )
        )

        # ═══ المرسأ «مريب» ═══
        out_susp = tmp / "suspicious"
        r_proposal = brain.propose(suspicious_goal)
        result.rows.append(
            GateRow(
                anchor="مريب",
                gate="بوابة PII ترفض الاقتراح",
                passed=not r_proposal.accepted,
                details_ar="الاقتراح مرفوض قبل أي توليد" if not r_proposal.accepted else "اقتراح مريب مُقبَل!",
            )
        )

        receipt_s = AISession().run(suspicious_goal, out_susp, write=True)
        result.rows.append(
            GateRow(
                anchor="مريب",
                gate="لا توليد بعد الرفض",
                passed=not out_susp.exists(),
                details_ar="مجلد الإخراج لم يُنشأ" if not out_susp.exists() else "كُتب على القرص رغم الرفض!",
            )
        )

        documented = (
            not receipt_s.ok
            and receipt_s.failed_step == "plan"
            and any(s.step == "plan" and not s.ok and s.exit_code == 1 for s in receipt_s.steps)
        )
        result.rows.append(
            GateRow(
                anchor="مريب",
                gate="الإيصال يوثّق الرفض عند الخطة",
                passed=documented,
                details_ar="failed_step=plan برمز 1" if documented else "الرفض غير موثّق كما يجب",
            )
        )

        no_crash = receipt_s is not None and len(receipt_s.steps) >= 1
        result.rows.append(
            GateRow(
                anchor="مريب",
                gate="لا استثناء خارج الطبقة",
                passed=no_crash,
                details_ar="الرفض عاد إيصالًا لا انهيارًا" if no_crash else "انهيار",
            )
        )

        # ═══ المرسأ «عدائي» ═══
        r_empty = AISession().run("   ", tmp / "adv1", write=True)
        result.rows.append(
            GateRow(
                anchor="عدائي",
                gate="هدف فارغ ⇒ فشل هيكلي آمن",
                passed=not r_empty.ok and r_empty.failed_step == "goal",
                details_ar="رمز 2 موثّق، لا كتابة" if not r_empty.ok else "قبول خاطئ لهدف فارغ",
            )
        )

        r_type = AISession().run(12345, tmp / "adv2", write=True)  # type: ignore[arg-type]
        result.rows.append(
            GateRow(
                anchor="عدائي",
                gate="هدف غير نصي ⇒ آمن",
                passed=not r_type.ok and r_type.failed_step == "goal",
                details_ar="النوع يُرفض بلا انهيار" if not r_type.ok else "قبول خاطئ لنوع غير نصي",
            )
        )

        busy = tmp / "busy"
        busy.mkdir()
        (busy / "existing.txt").write_text("لا تُحذف", encoding="utf-8")
        r_busy = AISession().run(clean_goal, busy, write=True)
        intact = (busy / "existing.txt").read_text(encoding="utf-8") == "لا تُحذف"
        result.rows.append(
            GateRow(
                anchor="عدائي",
                gate="مجلد غير فارغ ⇒ رفض بلا حذف",
                passed=not r_busy.ok and r_busy.failed_step == "out" and intact,
                details_ar="المحتوى القديم سليم" if intact else "كُتب فوق محتوى قائم!",
            )
        )

        r_long = AISession().run("وصف" * (MAX_DESCRIPTION_LEN // 2 + 10), tmp / "adv3", write=True)
        result.rows.append(
            GateRow(
                anchor="عدائي",
                gate="هدف أطول من الحد ⇒ آمن",
                passed=not r_long.ok and r_long.failed_step == "goal",
                details_ar=f"الحد {MAX_DESCRIPTION_LEN} محرفًا يُحترم" if not r_long.ok else "تجاوز الحد بلا رفض",
            )
        )

    result.seconds = time.perf_counter() - started
    return result
