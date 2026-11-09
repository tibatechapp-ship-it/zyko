"""zyko.workspace.report — المخرجات: JSON مهيكل + تقرير عربي RTL + سطر ملخص.

الإخراجان حتميان بافتراض include_timing=False (الافتراضي): نفس المجلد
⇒ نفس البايتات تمامًا، كما في المراجع والمُصلِح والحلقة. الوقت يظهر
فقط عند طلبه صراحة. كل ملاحظة في التقرير — أُصلحت أو بقيت — تعرض
suggestion_ar كما وردت، والملفات المتخطاة تعرض سببها العربي.
"""

from __future__ import annotations

import json
from typing import Any

from zyko.workspace.engine import (
    FILE_STATUS_AR,
    FILE_STATUS_SKIPPED,
    MAX_FILES,
    MAX_ROUNDS,
    SCHEMA,
    STAGE_AR,
    WRITE_INPLACE,
    WRITE_NONE,
    WorkspaceResult,
)

_LINE = "-" * 60

_WRITE_AR: dict[str, str] = {
    WRITE_NONE: "بلا كتابة (تجربة جافة)",
    "copy": "نسخة إلى مجلد جديد",
    WRITE_INPLACE: "تعديل موضعي مؤكَّد",
}


def workspace_result_to_json(result: WorkspaceResult, *, include_timing: bool = False) -> str:
    """حمولة JSON واحدة حتمية (ASCII عربي أصيل بلا هروب)."""
    return json.dumps(
        result.to_dict(include_timing=include_timing),
        ensure_ascii=False,
        indent=2,
    )


def workspace_summary_line(result: WorkspaceResult) -> str:
    """سطر واحد للملخص السريع في الطرفية وCI."""
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        return f"فشل في {stage}: {result.error_ar}"
    if result.verdict_ar.startswith("لا مراجعة"):
        return f"لا مراجعة: {result.verdict_ar}"
    return (
        f"فُحص {result.reviewed} ملفًا (تُخُطّي {result.skipped})"
        f" — عُدّل {result.changed_files}"
        f" — أُصلح {result.fixed_total}، يدوي {result.manual_total}، يبقى {result.open_total}"
        f" — الدرجة {result.min_score_before}←{result.min_score_after}/100"
        f" — الحكم: {result.verdict_ar}"
    )


def workspace_result_to_text(result: WorkspaceResult) -> str:
    """تقرير عربي مقروء لتشغيل المحرك على مجلد قائم — بلا رموز ثنائية الاتجاه."""
    lines: list[str] = []
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        lines.append(f"فشل المحرك في مرحلة {stage}")
        lines.append(f"السبب: {result.error_ar}")
        for p in result.problems:
            lines.append(f"  - {p}")
        return "\n".join(lines)

    lines.append("المحرك على أرض الواقع — مراجعة ← إصلاح لمجلد بايثون قائم")
    lines.append(f"المجلد: {result.src}")
    lines.append(
        f"الملفات: {result.files_total} بايثون (رُوجعت {result.reviewed}، تُخُطّي {result.skipped})"
        f" — الجولات: {result.rounds_ran}/{result.rounds_requested}"
        f" — الكتابة: {_WRITE_AR.get(result.write_mode, result.write_mode)}"
    )
    lines.append(
        f"المصائر: أُصلح {result.fixed_total} — يدوي {result.manual_total}"
        f" — يبقى {result.open_total} — عُدّل {result.changed_files} ملفًا"
    )
    if result.min_score_after is not None:
        lines.append(
            f"الدرجة: {result.min_score_before}←{result.min_score_after}/100"
            f" — الحكم النهائي: {result.verdict_ar}"
        )
    else:
        lines.append(f"الحكم النهائي: {result.verdict_ar}")
    if result.notes:
        for n in result.notes:
            lines.append(f"ملاحظة: {n}")
    if result.written:
        lines.append(f"كُتب على القرص: {len(result.written)} ملفًا مُصلَحًا (متحقق من صياغته)")
    if result.per_file:
        lines.append(_LINE)
        for f in result.per_file:
            if f["status"] == FILE_STATUS_SKIPPED:
                lines.append(f"[{f['path']}] تُخُطّي — {f.get('reason_ar', '')}")
                continue
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


def workspace_promise_text() -> str:
    """جدول ضمانات المحرك على المجلدات القائمة — للتوثيق و«promise» في CLI."""
    lines = [
        f"zyko.workspace (المخطط: {SCHEMA}) — سقف الجولات {MAX_ROUNDS} وسقف الملفات {MAX_FILES}",
        _LINE,
        "المسح    : ملفات بايثون بترتيب حتمي — بلا روابط رمزية وبلا مجلدات النظام",
        "المراجعة : 27 قاعدة AST ⇒ درجة 0–100 وملاحظات موقعها دقيق وكلها بـ suggestion_ar",
        "الإصلاح  : 12 مسارًا آمنًا + تحقق ast قبل القبول + اعتدال: على ناتجه لا يغيّر شيئًا",
        "الكتابة  : لا شيء افتراضيًا — نسخة لمجلد فارغ أو تعديل موضعي بتأكيد صريح",
        _LINE,
        "الفشل المهيكل: مجلد مفقود أو ملف بدل مجلد أو ترميز فاسد ⇒ رسالة عربية وخروج 2",
        "الخرج: تقرير عربي (JSON أو نص) حتمي البايتات — كل ملاحظة بـ suggestion_ar",
    ]
    return "\n".join(lines)


def workspace_payload_summary(result: WorkspaceResult) -> dict[str, Any]:
    """ملخص مضغوط للبوابات وأداة MCP: يُبنى من النتيجة بلا أي مصدر خارجي."""
    return {
        "schema": SCHEMA,
        "ok": result.ok,
        "failed_stage": result.failed_stage,
        "files_total": result.files_total,
        "reviewed": result.reviewed,
        "skipped": result.skipped,
        "changed_files": result.changed_files,
        "fixed": result.fixed_total,
        "manual": result.manual_total,
        "open": result.open_total,
        "min_score_before": result.min_score_before,
        "min_score_after": result.min_score_after,
        "verdict_ar": result.verdict_ar,
        "status_ar": FILE_STATUS_AR,
    }


__all__ = [
    "workspace_payload_summary",
    "workspace_promise_text",
    "workspace_result_to_json",
    "workspace_result_to_text",
    "workspace_summary_line",
]
