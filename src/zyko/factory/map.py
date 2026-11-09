"""zyko.factory.map — خريطة المصنع: وحداته وأوامره وعقوده الثلاثة.

المصنع ZYKO آلة واحدة مكتملة: توليد ← مراجعة ← إصلاح ← حارس، كل وحدة
فيه حتمية بلا نموذج وبلا شبكة، وكلها تُستدعى من بوابة واحدة ``zyko
factory``. وفوق هذا المصنع يُجمَّع لاحقًا ``zyko AI`` — طبقة الذكاء
التي تركب على آلة قابلة للتحقق لا على وعود.
"""

from __future__ import annotations

from zyko.version import __version__

_LINE = "=" * 66

_MAP_ROWS: tuple[tuple[str, str, str], ...] = (
    ("new", "zyko new --plan «وصف»", "المرحلة 1 — وصف عربي ⇒ مخطط ← موافقة ← مشروع"),
    (
        "fix",
        "zyko factory fix --path مجلد",
        "المرحلة 3 — إصلاح ملف/مجلد: 12 مسارًا آمنًا فوق 38 قاعدة",
    ),
    (
        "pipeline",
        "zyko factory pipeline --description «وصف» --out مجلد",
        "المرحلة 4 — توليد ← مراجعة ← إصلاح في أمر واحد",
    ),
    (
        "workspace",
        "zyko factory workspace --src مجلد",
        "المرحلة 5 — مراجعة ← إصلاح لأي مجلد قائم (تجربة جافة افتراضيًا)",
    ),
    (
        "baseline",
        "zyko factory baseline check --src مجلد",
        "المرحلة 6 — حارس الجودة: خط أساس حتمي وكشف تراجع بالأرقام",
    ),
    ("gates", "zyko factory gates", "بوابات المراحل 3+4+5+6 كاملة في أمر واحد"),
)


def factory_map_text() -> str:
    """خريطة المصنع — نفس النص لأمرَي map والتشغيل العاري."""
    lines = [
        f"المصنع ZYKO v{__version__} — آلة واحدة: توليد ← مراجعة ← إصلاح ← حارس",
        _LINE,
        "الوحدة     الأمر                                        ماذا تفعل",
    ]
    for name, cmd, what in _MAP_ROWS:
        lines.append(f"{name:<10} : {cmd}")
        lines.append(f"{'':<10}   {what}")
    lines.append(_LINE)
    lines.append("العقود الثلاثة (في كل وحدة):")
    lines.append("  1) حتمية بايتية: نفس المدخل ⇒ نفس البايتات — بلا نموذج وبلا شبكة")
    lines.append("  2) فشل مهيكل لا انهيار: مدخل عدائي ⇒ رسالة عربية وخروج 2")
    lines.append("  3) كل ملاحظة تحمل suggestion_ar كما وردت — أُصلحت أم بقيت")
    lines.append("أكواد الخروج: 0 سليم/مقبول — 1 ملاحظات متبقية/بوابة فاشلة — 2 خطأ استخدام")
    lines.append(
        "الكتابة على قرصك: لا شيء افتراضيًا — خط الأساس وحده يكتبه update، والموضعي بـ --yes"
    )
    lines.append(f"وفوق هذا المصنع يُجمَّع zyko AI — طبقة ذكاء على آلة قابلة للتحقق (v{__version__})")
    return "\n".join(lines)


__all__ = ["factory_map_text"]
