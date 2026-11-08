"""قواعد فحص CSS — ماسح أقواس يدوي حتمي (يدعم التداخل مثل @media).

المبدأ: نمرّ على الشيفرة محرفًا محرفًا بعد تعطيل التعليقات (مع حفظ الإزاحات)،
نجمّع كومة المحددات selectors، ونحلل تصريحات كل كتلة ورقية بلا أقواس.
سياق RTL يُستنتج من أي محدد في السلسلة ([dir=rtl] أو :dir(rtl) أو صنف يحوي rtl)
أو من تصريح direction: rtl داخل الكتلة نفسها.
"""

from __future__ import annotations

import re

from .core import Finding, excerpt_of, line_col_of

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# محددات تعلن سياق RTL: [dir=rtl] / [dir="rtl"] / :dir(rtl) / صنف يحوي rtl
_RTL_SELECTOR_RE = re.compile(
    r"""\[\s*dir\s*=\s*["']?rtl["']?\s*\]   # [dir=rtl]
      | :dir\(\s*rtl\s*\)                   # :dir(rtl)
      | \.[-\w]*rtl[-\w]*                   # .rtl / .dir-rtl / .is-rtl
    """,
    re.IGNORECASE | re.VERBOSE,
)

# خصائص فيزيائية يمين/يسار → الجذر المنطقي المقابل
_PHYSICAL_BASE = {
    "margin-left": "margin-inline",
    "margin-right": "margin-inline",
    "padding-left": "padding-inline",
    "padding-right": "padding-inline",
    "border-left": "border-inline",
    "border-right": "border-inline",
}

_DECL_RE = re.compile(r"([-\w]+)\s*:\s*([^;{}]+)")

_INLINE_SIDE = {"left": "inline-start", "right": "inline-end"}


def _blank(m: re.Match) -> str:  # noqa: ARG001
    return " " * (m.end() - m.start())


def _iter_blocks(css_clean: str):
    """يمرّ على الكتل مرة واحدة ويرجع (كومة المحددات، متن الكتلة، إزاحة المتن).

    الكتل الأم (@media وإن شابه) تُمرَّر في الكومة لكن لا تُحلَّل تصريحاتها
    لأن متونها تحوي أقواسًا متداخلة.
    """
    stack: list[tuple[str, int]] = []  # (selector, body_start)
    sel_start = 0
    i = 0
    n = len(css_clean)
    while i < n:
        ch = css_clean[i]
        if ch == "{":
            stack.append((css_clean[sel_start:i].strip(), i + 1))
            sel_start = i + 1
        elif ch == "}":
            if stack:
                selector, body_start = stack.pop()
                body = css_clean[body_start:i]
                if "{" not in body:  # كتلة ورقية فقط
                    snapshot = [s for s, _ in stack] + [selector]
                    yield snapshot, body, body_start
                sel_start = i + 1
        i += 1


def _declarations(body: str):
    """يستخرج (خاصية، قيمة، إزاحة نسبية) من متن كتلة ورقية."""
    for m in _DECL_RE.finditer(body):
        yield m.group(1).lower(), m.group(2).strip().lower(), m.start(1)


def check_css(
    css: str,
    filename: str = "<inline>",
    base_rtl: bool = False,
) -> list[Finding]:
    """يفحص نص CSS ويرجع قائمة الملاحظات (حتمي بالكامل).

    base_rtl: يضبط السياق الافتراضي لكل الكتل — يستخدم عند فحص <style>
    داخل مستند dir="rtl" حتى ترث قواعده اتجاه المستند.
    """
    findings: list[Finding] = []
    css_clean = _COMMENT_RE.sub(_blank, css)  # تعطيل التعليقات مع حفظ الإزاحات

    for stack, body, body_start in _iter_blocks(css_clean):
        rtl_ctx = base_rtl or any(_RTL_SELECTOR_RE.search(s) for s in stack if s)
        decls = list(_declarations(body))
        # الكتلة التي تعلن direction: rtl تُعدّ سياق RTL لنفسها
        if any(p == "direction" and "rtl" in v for p, v, _ in decls):
            rtl_ctx = True

        for prop, value, rel in decls:
            offset = body_start + rel
            line, col = line_col_of(css, offset)
            excerpt = excerpt_of(css, offset)

            if prop == "text-align":
                side = value.split()[0] if value.split() else ""
                if side == "left" and rtl_ctx:
                    findings.append(
                        Finding(
                            "RTL-CSS-001",
                            "error",
                            "text-align: left داخل سياق RTL — الفقرة تلتصق بالجهة المعاكسة للقراءة",
                            filename,
                            line,
                            col,
                            excerpt,
                            "استخدم text-align: right أو الأفضل start (يتكيف مع الاتجاه تلقائيًا)",
                        )
                    )
                elif side in ("left", "right"):
                    findings.append(
                        Finding(
                            "RTL-CSS-002",
                            "warning",
                            f"text-align: {side} قيمة فيزيائية — تنعكس جهتها في سياقات RTL",
                            filename,
                            line,
                            col,
                            excerpt,
                            "استخدم start بدلًا من left و end بدلًا من right",
                        )
                    )

            elif prop in _PHYSICAL_BASE:
                base = _PHYSICAL_BASE[prop]
                findings.append(
                    Finding(
                        "RTL-CSS-003",
                        "error" if rtl_ctx else "warning",
                        (
                            f"{prop} خاصية فيزيائية — في RTL تُرسم على الجهة المعاكسة من المقصود"
                            if rtl_ctx
                            else f"{prop} خاصية فيزيائية تنعكس جهتها في سياقات RTL"
                        ),
                        filename,
                        line,
                        col,
                        excerpt,
                        f"استخدم {base}-start أو {base}-end حسب القصد الاتجاهي",
                    )
                )

            elif prop == "float" and value in _INLINE_SIDE:
                findings.append(
                    Finding(
                        "RTL-CSS-004",
                        "warning",
                        f"float: {value} قيمة فيزيائية تنقلب في RTL",
                        filename,
                        line,
                        col,
                        excerpt,
                        f"استخدم float: {_INLINE_SIDE[value]}",
                    )
                )

            elif prop in ("left", "right") and value != "auto":
                findings.append(
                    Finding(
                        "RTL-CSS-005",
                        "info",
                        f"إزاحة تموضع فيزيائية «{prop}» — تعني جهة مختلفة حسب اتجاه المستند",
                        filename,
                        line,
                        col,
                        excerpt,
                        "فكّر في inset-inline-start/end أو الاختصار المنطقي inset",
                    )
                )

    return findings
