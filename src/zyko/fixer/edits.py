"""zyko.fixer.edits — طبقة التحرير النصي الحتمية: قطع موقعة لا إعادة توليد.

المبدأ: المُصلِح لا يعيد توليد الملف بـ ast.unparse (فقدان التعليقات والتنسيق)،
بل يطبق «قطعًا» Edits موقعة بسطر وعمود على النص الأصلي — فيبقى كل ما لم
تلمسه القاعدة كما هو حرفيًا.

تنبيه دقيق (فخ الإحداثيات): أعمدة AST في بايثون هي **إزاحات بايت UTF-8**
داخل السطر لا إزاحات حروف — والأسطر العربية شائعة في هذا المشروع. كل قراءة
موقع تمر من هنا: التحويل بايت⇄حرف، وتقطيع المقاطع، وإدراج المسافات.

تطبيق القطع: من النهاية إلى البداية، والقطع المتداخلة تُسقَط (لا انهيار
ولا صمت غير موثق — السقوط يُرجع بقائمة skipped للتفسير العربي).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

__all__ = ["Edit", "SourceText", "apply_edits", "indent_of", "parses", "shift_lines"]


@dataclass(frozen=True)
class Edit:
    """قطعة تحرير واحدة: نطاق (سطر، عمود بايت) ⇒ نص بديل — موقعة بالقاعدة."""

    line: int  # 1-based
    col: int  # إزاحة بايت 0-based داخل السطر (اصطلاح AST)
    end_line: int
    end_col: int
    replacement: str
    rule_id: str
    note_ar: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "line": self.line,
            "col": self.col + 1,
            "end_line": self.end_line,
            "end_col": self.end_col + 1,
            "note_ar": self.note_ar,
        }


class SourceText:
    """نص المصدر مع فهرسة الأسطر وتحويل إحداثيات بايت AST ⇄ مواضع حرفية."""

    __slots__ = ("text", "_lines", "_starts")

    def __init__(self, source: str) -> None:
        self.text = source
        self._lines = source.split("\n")
        starts = [0]
        for line_text in self._lines[:-1]:
            starts.append(starts[-1] + len(line_text) + 1)  # +1 لفاصل السطر
        self._starts = starts

    # ------------------------------------------------------------- الأسطر
    def line_count(self) -> int:
        return len(self._lines)

    def line_text(self, line: int) -> str:
        """نص سطر (1-based) — خارج النطاق يُقص حتميًا إلى أقرب سطر سليم."""
        idx = min(max(line, 1), len(self._lines)) - 1
        return self._lines[idx]

    def line_start(self, line: int) -> int:
        idx = min(max(line, 1), len(self._lines)) - 1
        return self._starts[idx]

    # --------------------------------------------------------- الإحداثيات
    @staticmethod
    def char_col(line_text: str, byte_col: int) -> int:
        """إزاحة بايت داخل السطر ⇒ إزاحة حرف. الفهارس الخارجة تُقص بأمان."""
        raw = line_text.encode("utf-8")
        byte_col = min(max(byte_col, 0), len(raw))
        return len(raw[:byte_col].decode("utf-8", errors="replace"))

    def abs_pos(self, line: int, byte_col: int) -> int:
        """موقع مطلق حرفي في النص الكامل من (سطر، عمود بايت)."""
        return self.line_start(line) + self.char_col(self.line_text(line), byte_col)

    def segment(self, start_line: int, start_col: int, end_line: int, end_col: int) -> str:
        """قصّ مقطع المصدر بين موقعين بإحداثيات AST — كما كتبه المؤلف حرفيًا."""
        a = self.abs_pos(start_line, start_col)
        b = self.abs_pos(end_line, end_col)
        if b < a:
            return ""
        return self.text[a:b]


def apply_edits(source: str, edits: list[Edit]) -> tuple[str, list[Edit], list[tuple[Edit, str]]]:
    """تطبيق القطع كلها دفعة واحدة: من النهاية إلى البداية، والتداخل يُسقَط.

    ترجع (النص الجديد، القطع المطبقة، القطع المسقطة مع سبب عربي لكل واحدة).
    """
    st = SourceText(source)
    decorated: list[tuple[int, int, Edit]] = []
    for e in edits:
        try:
            a = st.abs_pos(e.line, e.col)
            b = st.abs_pos(e.end_line, e.end_col)
        except Exception:  # noqa: BLE001 — موقع معطوب يُسقط قطعته ولا يُسقط التطبيق
            continue
        if b < a:
            continue
        decorated.append((a, b, e))
    # ترتيب حتمي: من الآخر للبداية، وعند التساوي الأوسع نطاقًا أولًا.
    decorated.sort(key=lambda t: (t[0], t[1]), reverse=True)
    out = st.text
    applied: list[Edit] = []
    skipped: list[tuple[Edit, str]] = []
    cursor = len(out)  # بداية أقصى منطقة مُعدَّلة حتى الآن
    for a, b, e in decorated:
        if b > cursor:
            skipped.append((e, "تداخل مع قطعة أخرى طبقت قبله — أُسقطت لسلامة النص"))
            continue
        out = out[:a] + e.replacement + out[b:]
        cursor = a
        applied.append(e)
    applied.reverse()  # نرجعها بترتيب المصدر الطبيعي للعرض الحتمي
    skipped.reverse()
    return out, applied, skipped


def indent_of(line_text: str) -> str:
    """البادئة الفارغة لبداية السطر (مسافات/جدوات كما هي)."""
    return line_text[: len(line_text) - len(line_text.lstrip())]


def shift_lines(block: str, delta: int) -> str:
    """إزاحة كتلة أسطر أفقيًا بمقدار delta (سالب يقصّ من البادئة بأمان)."""
    if delta == 0:
        return block
    lines = block.split("\n")
    out: list[str] = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
        elif delta > 0:
            out.append(" " * delta + ln)
        else:
            cut = min(-delta, len(ln) - len(ln.lstrip()))
            out.append(ln[cut:])
    return "\n".join(out)


def parses(source: str) -> bool:
    """هل النص يُحلَّل كشيفرة بايثون سليمة؟ — بوابة التحقق بعد كل إصلاح."""
    try:
        ast.parse(source)
        return True
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
