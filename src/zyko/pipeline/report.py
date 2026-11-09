"""zyko.pipeline.report — المخرجات: JSON مهيكل + تقرير عربي RTL + سطر ملخص.

الإخراجان حتميان بافتراض include_timing=False (الافتراضي): نفس الحلقة
⇒ نفس البايتات تمامًا، كما في المراجع والمُصلِح. الوقت يظهر فقط عند
طلبه صراحة؛ تبقى حمولات CI والاختبارات والبوابات موقّعة بايتيًا.
كل ملاحظة في التقرير — أُصلحت أو بقيت — تعرض suggestion_ar كما وردت.
"""

from __future__ import annotations

import json
from typing import Any

from zyko.pipeline.engine import MAX_DESCRIPTION_LEN, MAX_ROUNDS, SCHEMA, STAGE_AR, PipelineResult

_LINE = "-" * 60


def pipeline_result_to_json(result: PipelineResult, *, include_timing: bool = False) -> str:
    """حمولة JSON واحدة حتمية (ASCII عربي أصيل بلا هروب)."""
    return json.dumps(
        result.to_dict(include_timing=include_timing),
        ensure_ascii=False,
        indent=2,
    )


def pipeline_summary_line(result: PipelineResult) -> str:
    """سطر واحد للملخص السريع في الطرفية وCI."""
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        return f"فشل في {stage}: {result.error_ar}"
    return (
        f"الحلقة اكتملت: {len(result.files)} ملفًا، عُدّل {result.changed_files}"
        f" — أُصلح {result.fixed_total}، يدوي {result.manual_total}، يبقى {result.open_total}"
        f" — الدرجة {result.min_score_before}←{result.min_score_after}/100"
        f" — الحكم: {result.verdict_ar}"
    )


def pipeline_result_to_text(result: PipelineResult) -> str:
    """تقرير عربي مقروء للحلقة كاملة — بلا رموز ثنائية الاتجاه إطلاقًا."""
    lines: list[str] = []
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        lines.append(f"فشلت الحلقة في مرحلة {stage}")
        lines.append(f"السبب: {result.error_ar}")
        for p in result.problems:
            lines.append(f"  - {p}")
        return "\n".join(lines)

    plan = result.plan or {}
    lines.append("حلقة التغذية الراجعة — توليد ← مراجعة ← إصلاح (أمر واحد)")
    lines.append(f"الوصف: {result.description[:120]}")
    lines.append(
        f"المخطط: {plan.get('name', '؟')} ({plan.get('template', '؟')})"
        f" — الوحدات: {'، '.join(plan.get('modules', [])) or 'لا شيء'}"
    )
    lines.append(
        f"الملفات المولّدة: {len(result.files)} (المُراجَعة: {len(result.py_files)} بايثون)"
        f" — الجولات: {result.rounds_ran}/{result.rounds_requested}"
    )
    lines.append(
        f"المصائر: أُصلح {result.fixed_total} — يدوي {result.manual_total}"
        f" — يبقى {result.open_total} — عُدّل {result.changed_files} ملفًا"
    )
    lines.append(
        f"الدرجة: {result.min_score_before}←{result.min_score_after}/100"
        f" — الحكم النهائي: {result.verdict_ar}"
    )
    if result.notes:
        for n in result.notes:
            lines.append(f"ملاحظة: {n}")
    if result.written:
        lines.append(f"كُتب على القرص: {len(result.written)} ملفًا مُصلَحًا (متحقق من صياغته)")
    if result.per_file:
        lines.append(_LINE)
        for f in result.per_file:
            arrow = "→" if f["changed"] else "="
            lines.append(
                f"[{f['path']}] {f['score_before']} {arrow} {f['score_after']}"
                f" — {f['verdict_after_ar']}"
                f" (أُصلح {f['fixed_count']}، يدوي {f['manual_count']}، يبقى {f['open_count']})"
            )
            for o in f["outcomes"]:
                loc = f"سطر {o['line']} عمود {o['col']}"
                lines.append(
                    f"  [{o['severity_ar']}] {loc} {o['rule_id']} — {o['status_ar']}: {o['message_ar']}"
                )
                lines.append(f"      الإصلاح: {o['suggestion_ar']}")
                if o["status"] != "fixed":
                    lines.append(f"      الإجراء: {o['action_ar']}")
    return "\n".join(lines)


def stages_table_text() -> str:
    """جدول مراحل الحلقة وضمانات كل مرحلة — للتوثيق و«stages» في CLI."""
    rows = (
        (
            "coder",
            "التوليد",
            "مخطط متحقق من وصف عربي ⇒ شجرة ملفات كاملة في الذاكرة قبل أي كتابة",
        ),
        (
            "reviewer",
            "المراجعة",
            "27 قاعدة AST ⇒ درجة 0–100 وملاحظات موقعها دقيق وكلها بـ suggestion_ar",
        ),
        (
            "fixer",
            "الإصلاح",
            "12 مسارًا آمنًا + تحقق ast قبل القبول + اعتدال: على ناتجه لا يغيّر شيئًا",
        ),
    )
    lines = [
        f"حلقة zyko.pipeline (المخطط: zyko.pipeline/1) — سقف الجولات {MAX_ROUNDS}"
        f" وحد الوصف {MAX_DESCRIPTION_LEN} محرفًا",
        _LINE,
    ]
    for stage, ar, promise in rows:
        lines.append(f"{stage} — {STAGE_AR[stage]}: {promise}")
    lines.append(_LINE)
    lines.append("الخرج: مشروع مُصلَح على القرص + تقرير عربي (JSON أو نص) حتمي البايتات")
    return "\n".join(lines)


def pipeline_payload_summary(result: PipelineResult) -> dict[str, Any]:
    """ملخص مضغوط للبوابات: يُبنى من النتيجة بلا أي مصدر خارجي."""
    return {
        "schema": SCHEMA,
        "ok": result.ok,
        "failed_stage": result.failed_stage,
        "files": len(result.files),
        "py_files": len(result.py_files),
        "changed_files": result.changed_files,
        "fixed": result.fixed_total,
        "manual": result.manual_total,
        "open": result.open_total,
        "min_score_before": result.min_score_before,
        "min_score_after": result.min_score_after,
        "verdict_ar": result.verdict_ar,
    }


__all__ = [
    "pipeline_payload_summary",
    "pipeline_result_to_json",
    "pipeline_result_to_text",
    "pipeline_summary_line",
    "stages_table_text",
]
