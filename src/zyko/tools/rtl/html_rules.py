"""قواعد فحص HTML — ماسح وسوم بلا اعتماديات (regex حتمي).

يفحص:
  RTL-HTML-001: مستند عربي بلا dir على <html>
  RTL-HTML-002: dir=rtl بلا lang
  RTL-HTML-003: عنصر نصي بنص عربي بلا dir داخل مستند LTR
  RTL-HTML-004: style="text-align: left" داخل عنصر RTL
كما يستخرج كتل <style> ويمررها على فاحص CSS (مع تصحيح أرقام الأسطر).

التتبع: كومة عناصر مفتوحة — كل نص حر يُنسب لأعمق عنصر مفتوح، وكل عنصر
يُبلغ مرة واحدة كحد أقصى لكل مقطع نصي له (أعمق عنصر فقط).
"""

from __future__ import annotations

import re

from .core import (
    ARABIC_LETTER_RE,
    Finding,
    arabic_letter_ratio,
    excerpt_of,
    has_arabic,
    line_col_of,
)
from .css_rules import check_css

# وسم مع محارفه: </div> / <div / <br/> — مع دعم علامات الاقتباس داخل الخصائص
_TAG_RE = re.compile(r"<(/?)\s*([a-zA-Z][-\w]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>")

_ATTR_RE = re.compile(r"([:\-\w]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")

_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)

_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

# الوسوم النصية التي يستحق نصها فحص RTL-HTML-003 (حاويات ووسوم تأكيد)
_TEXT_TAGS = {
    "title",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "td",
    "th",
    "div",
    "span",
    "a",
    "button",
    "label",
    "blockquote",
    "figcaption",
    "caption",
    "dd",
    "dt",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "small",
    "summary",
}

_ALIGN_LEFT_RE = re.compile(r"text-align\s*:\s*left", re.IGNORECASE)


def _parse_attrs(attr_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_text):
        value = m.group(2)
        if value[:1] in ('"', "'"):
            value = value[1:-1]
        attrs[m.group(1).lower()] = value
    return attrs


def check_html(source: str, filename: str = "<inline>") -> list[Finding]:
    """يفحص مستند HTML ويرجع الملاحظات (حتمي بالكامل)."""
    findings: list[Finding] = []
    m_html = re.search(r"<html\b[^>]*>", source, re.IGNORECASE)
    html_attrs = _parse_attrs(m_html.group(0)) if m_html else {}
    html_dir = html_attrs.get("dir", "").strip().lower()
    doc_is_rtl = html_dir == "rtl"

    # ---- RTL-HTML-001: مستند عربي بلا dir
    # الحكم على المصدر الخام كله: عربي محقون من سكربت يحتاج dir أيضًا
    if m_html is not None:
        if "dir" not in html_attrs and has_arabic(source):
            line, col = line_col_of(source, m_html.start())
            findings.append(
                Finding(
                    "RTL-HTML-001",
                    "error",
                    "مستند يحوي نصًا عربيًا بلا dir على <html> — المتصفح سيقصّه كأنه LTR",
                    filename,
                    line,
                    col,
                    excerpt_of(source, m_html.start()),
                    'أضف dir="rtl" lang="ar" إلى وسم <html>',
                )
            )
    elif has_arabic(source):
        findings.append(
            Finding(
                "RTL-HTML-001",
                "warning",
                "مقتطف عربي بلا وسم <html> جذر — لا سياق اتجاه محدد",
                filename,
                1,
                1,
                excerpt_of(source, 0),
                'ضع <html dir="rtl" lang="ar"> كجذر للمستند',
            )
        )

    # ---- RTL-HTML-002: dir=rtl بلا lang
    if m_html is not None and doc_is_rtl and "lang" not in html_attrs:
        line, col = line_col_of(source, m_html.start())
        findings.append(
            Finding(
                "RTL-HTML-002",
                "warning",
                'dir="rtl" بلا lang — القارئات الصوتية واختيار الخطوط تعتمد على lang',
                filename,
                line,
                col,
                excerpt_of(source, m_html.start()),
                'أضف lang="ar" إلى وسم <html>',
            )
        )

    # ---- المرور الرئيسي: كومة عناصر مفتوحة
    reported: set[int] = set()  # إزاحات عناصر بلُغت بالفعل (منع التكرار)
    open_stack: list[tuple[str, dict[str, str], int]] = []
    prev_end = 0  # نهاية آخر وسم معالج

    def flush_text(text_end: int) -> None:
        """يفحص النص الحر بين آخر وسم والوسم الحالي."""
        if not open_stack or doc_is_rtl:
            return
        text = source[prev_end:text_end]
        if not text.strip():
            return
        # أعمق عنصر نصي مفتوح بلا dir ولم يُبلغ سابقًا
        for tag, attrs, offset in reversed(open_stack):
            if tag in _TEXT_TAGS and "dir" not in attrs and offset not in reported:
                if _is_clearly_arabic(text):
                    reported.add(offset)
                    line, col = line_col_of(source, offset)
                    findings.append(
                        Finding(
                            "RTL-HTML-003",
                            "warning",
                            f"نص عربي داخل <{tag}> بلا dir في مستند LTR — قد يُعرض بعكس الترتيب",
                            filename,
                            line,
                            col,
                            excerpt_of(source, offset),
                            f'أضف dir="rtl" إلى <{tag}> أو اضبط dir="rtl" على الجذر',
                        )
                    )
                return  # أعمق عنصر فقط مهما كانت النتيجة

    for m in _TAG_RE.finditer(source):
        closing, tag, attr_text, self_close = (
            m.group(1),
            m.group(2).lower(),
            m.group(3),
            bool(m.group(4)),
        )

        if not closing:  # فتح
            flush_text(m.start())
            attrs = _parse_attrs(attr_text)

            # RTL-HTML-004: محاذاة يسار داخلية على عنصر RTL
            style_attr = attrs.get("style", "")
            own_dir = attrs.get("dir", "").strip().lower()
            if (
                style_attr
                and _ALIGN_LEFT_RE.search(style_attr)
                and (own_dir == "rtl" or doc_is_rtl)
            ):
                line, col = line_col_of(source, m.start())
                findings.append(
                    Finding(
                        "RTL-HTML-004",
                        "error",
                        "محاذاة left داخلية على عنصر في مستند RTL — النص يلتصق بالجهة الخطأ",
                        filename,
                        line,
                        col,
                        excerpt_of(source, m.start()),
                        'استخدم style="text-align: start" أو احذف المحاذاة الداخلية',
                    )
                )

            if tag not in _VOID_ELEMENTS and not self_close:
                open_stack.append((tag, attrs, m.start()))
            prev_end = m.end()

        else:  # إغلاق
            flush_text(m.start())
            # أفرغ الكومة حتى العنصر المطابق (تسامح مع HTML غير متوازن)
            while open_stack:
                open_tag, _, _ = open_stack.pop()
                if open_tag == tag:
                    break
            prev_end = m.end()

    flush_text(len(source))

    # ---- كتل <style> → فاحص CSS مع تصحيح أرقام الأسطر ووراثة اتجاه المستند
    for m_style in _STYLE_RE.finditer(source):
        css_body = m_style.group(1)
        base_line = source.count("\n", 0, m_style.start(1)) + 1
        for f in check_css(css_body, f"{filename}#<style>", base_rtl=doc_is_rtl):
            f.line += base_line - 1
            findings.append(f)

    return findings


def _is_clearly_arabic(text: str) -> bool:
    """نص عربي واضح: ≥3 حروف عربية وتشكل ≥40% من حروفه."""
    stripped = text.strip()
    arabic_letters = len(ARABIC_LETTER_RE.findall(stripped))
    return arabic_letters >= 3 and arabic_letter_ratio(stripped) >= 0.4
