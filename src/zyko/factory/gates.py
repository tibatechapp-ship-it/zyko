"""zyko.factory.gates — بوابات المصنع الثلاث في استدعاء واحد.

تجمع بوابات قبول المراحل (3: المُصلِح، 4: الحلقة، 5: المجلدات القائمة)
في جدول خلاصة واحد: كل بوابة ستُّ بوابات كمية على مراسٍ عربية، والمجموع
18 بوابه. الحكم إجمالي: «المصنع مقبول» فقط إذا نجحت الثلاث كلها —
نفس نقطة الدخول للاختبارات وللـ CI وللطرفية.
"""

from __future__ import annotations

from typing import Any

_GATE_LINE = "-" * 52


def run_all_gates(*, max_seconds: float = 5.0) -> list[tuple[str, Any]]:
    """شغّل بوابات المراحل الثلاث وأعدها بترتيبها — بلا طباعة."""
    from zyko.fixer.gate import run_phase3_gate
    from zyko.pipeline.gate import run_phase4_gate
    from zyko.workspace.gate import run_phase5_gate

    return [
        ("المرحلة 3 — المُصلِح", run_phase3_gate(max_seconds=max_seconds)),
        ("المرحلة 4 — الحلقة", run_phase4_gate(max_seconds=max_seconds)),
        ("المرحلة 5 — المجلدات القائمة", run_phase5_gate(max_seconds=max_seconds)),
    ]


def combined_gates_text(gates: list[tuple[str, Any]]) -> str:
    """النص الكامل: جدول كل بوابة ثم خلاصة إجمالية موقعة."""
    parts: list[str] = ["بوابات المصنع الثلاث (18 بوابه على مراسٍ عربية)", _GATE_LINE]
    for label, gate in gates:
        parts.append(f"[{label}]")
        parts.append(gate.table_ar())
        parts.append(_GATE_LINE)
    passed = sum(1 for _, g in gates if g.ok)
    verdict = "المصنع مقبول ✅" if passed == len(gates) else "المصنع مرفوض ❌"
    parts.append(f"الخلاصة: {passed}/{len(gates)} بوابات مراحل ناجحة — الحكم: {verdict}")
    return "\n".join(parts)


__all__ = ["combined_gates_text", "run_all_gates"]
