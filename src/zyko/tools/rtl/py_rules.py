"""قواعد فحص بايثون — ast قياسي، حتمي بالكامل.

RTL-PY-000: ملف غير صالح التركيب (خطأ)
RTL-PY-001: مقارنة سلسلة عربية بسلسلة لاتينية أو أرقام عربية-هندية بغربية (خطأ)
RTL-PY-002: سلسلة رسائل مختلطة عربي/لاتيني بلا محارف اتجاه (معلومة)
RTL-PY-003: محارف تحكم اتجاه مخفية — Trojan Source (خطأ)
RTL-PY-004: معرّفات بأرقام عربية-هندية أو خليط عربي/لاتيني (تحذير)
"""

from __future__ import annotations

import ast

from .core import (
    ARABIC_INDIC_DIGITS_RE,
    ARABIC_LETTER_RE,
    ASCII_DIGITS_RE,
    BIDI_CONTROL_RE,
    BIDI_MARKS_RE,
    LATIN_LETTER_RE,
    Finding,
    excerpt_of,
    line_col_of,
)

_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)

_BIDI_NAME = "U+202A–U+202E / U+2066–U+2069"


# ---------------------------------------------------------------- أدوات


def _const_str(node: ast.AST) -> str | None:
    """قيمة السلسلة إذا كانت العقدة ثابتًا نصيًا، وإلا None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _collection_consts(node: ast.AST) -> list[str] | None:
    """الثوابت النصية داخل tuple/list/set إذا كانت كلها سلاسل، وإلا None."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        elems = node.elts
        consts = [_const_str(e) for e in elems]
        if consts and all(c is not None for c in consts):
            return consts  # type: ignore[return-value]
    return None


def _mixed_scripts(values: list[str]) -> bool:
    """هل تختلط القائمة بين عناصر بحروف عربية وعناصر لاتينية فقط؟"""
    has_ar = any(ARABIC_LETTER_RE.search(v) for v in values)
    has_lat = any(LATIN_LETTER_RE.search(v) and not ARABIC_LETTER_RE.search(v) for v in values)
    return has_ar and has_lat


def _letters_mismatch(x: str, y: str) -> bool:
    """طرف بحروف عربية والآخر بحروف لاتينية فقط."""
    x_ar, y_ar = bool(ARABIC_LETTER_RE.search(x)), bool(ARABIC_LETTER_RE.search(y))
    if x_ar == y_ar:
        return False
    other = y if x_ar else x
    return bool(LATIN_LETTER_RE.search(other))


def _digits_mismatch(x: str, y: str) -> bool:
    """طرف بأرقام عربية-هندية والآخر بأرقام غربية (بلا حروف عربية تفسّرها)."""
    x_ad = bool(ARABIC_INDIC_DIGITS_RE.search(x))
    y_ad = bool(ARABIC_INDIC_DIGITS_RE.search(y))
    if x_ad == y_ad:
        return False
    if x_ad:
        return bool(ASCII_DIGITS_RE.search(y)) and not ARABIC_LETTER_RE.search(y)
    return bool(ASCII_DIGITS_RE.search(x)) and not ARABIC_LETTER_RE.search(x)


def _is_mixed_message(text: str) -> bool:
    """سلسلة رسائل مختلطة: حروف عربية + لاتينية + فراغات، بلا علامات اتجاه.

    علامتا LRM/RLM (U+200E/U+200F) هي الإصلاح الموصى به — وجودها يسكت القاعدة.
    """
    if len(text) < 12 or " " not in text:
        return False
    if BIDI_MARKS_RE.search(text):
        return False
    return bool(ARABIC_LETTER_RE.search(text)) and bool(LATIN_LETTER_RE.search(text))


def _identifier_issue(name: str) -> str | None:
    """مشكلة معرّف: أرقام عربية-هندية، أو خليط حروف عربية ولاتينية."""
    if ARABIC_INDIC_DIGITS_RE.search(name):
        return "أرقام عربية-هندية"
    if ARABIC_LETTER_RE.search(name) and LATIN_LETTER_RE.search(name):
        return "خليط حروف عربية ولاتينية"
    return None


def _offset_of(source: str, lineno: int, col_offset: int) -> int:
    """إزاحة مطلقة من (سطر، عمود)."""
    lines = source.split("\n")
    return sum(len(ln) + 1 for ln in lines[: lineno - 1]) + col_offset


def _node_offset(source: str, node: ast.AST) -> int:
    return _offset_of(source, getattr(node, "lineno", 1), getattr(node, "col_offset", 0))


# ---------------------------------------------------------------- الفاحص


def check_python(source: str, filename: str = "<inline>") -> list[Finding]:
    """يفحص شيفرة بايثون ويرجع الملاحظات (حتمي بالكامل)."""
    findings: list[Finding] = []

    # ---- RTL-PY-003: محارف اتجاه مخفية (فوق كل شيء — ثغرة أمنية)
    for m in BIDI_CONTROL_RE.finditer(source):
        line, col = line_col_of(source, m.start())
        findings.append(
            Finding(
                "RTL-PY-003",
                "error",
                "محرف تحكم اتجاه مخفي في الشيفرة — ثغرة Trojan Source (CVE-2021-42574)",
                filename,
                line,
                col,
                excerpt_of(source, m.start()),
                f"احذف محارف {_BIDI_NAME} نهائيًا — تُخفي المنطق عن العين والمراجعة",
            )
        )

    # ---- RTL-PY-000: صلاحية التركيب
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        findings.append(
            Finding(
                "RTL-PY-000",
                "error",
                f"ملف بايثون غير صالح التركيب: {exc.msg}",
                filename,
                exc.lineno or 1,
                exc.offset or 1,
                (exc.text or "").strip()[:120],
                "أصلح خطأ التركيب قبل أي معالجة أخرى — باقي القواعد تحتاج شجرة صالحة",
            )
        )
        return findings

    # ---- المرور على الشجرة
    seen_names: set[str] = set()  # نفس المعرّف يُبلَّغ مرة واحدة لكل ملف
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            _check_compare(node, source, filename, findings)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _check_identifier(node.name, node, source, filename, findings, seen_names)

        elif isinstance(node, ast.Name):
            _check_identifier(node.id, node, source, filename, findings, seen_names)

        elif isinstance(node, ast.arg):
            _check_identifier(node.arg, node, source, filename, findings, seen_names)

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_mixed_message(node.value):
                _add_mixed_finding(source, node, filename, findings)

        elif isinstance(node, ast.JoinedStr):
            # الأجزاء الحرفية تُدرس مجمّعة — الخلط قد يمتد عبر الاستقراء
            literals = "".join(
                p.value
                for p in node.values
                if isinstance(p, ast.Constant) and isinstance(p.value, str)
            )
            if _is_mixed_message(literals):
                _add_mixed_finding(source, node, filename, findings)

    return findings


# ---------------------------------------------------------------- قواعد فرعية


def _check_compare(node: ast.Compare, source: str, filename: str, findings: list[Finding]) -> None:
    operands = [node.left, *node.comparators]
    for i in range(len(operands) - 1):
        if i >= len(node.ops) or not isinstance(node.ops[i], _COMPARE_OPS):
            continue
        a, b = _const_str(operands[i]), _const_str(operands[i + 1])

        # حالة العضوية: x in (...) بقائمة تخلط عربيًا ولاتينيًا
        if isinstance(node.ops[i], (ast.In, ast.NotIn)):
            for side in (operands[i], operands[i + 1]):
                consts = _collection_consts(side)
                if consts and _mixed_scripts(consts):
                    _fire_compare(
                        node,
                        source,
                        filename,
                        findings,
                        "قائمة عضو تخلط قيمًا عربية وقيمًا لاتينية — حالتان لنفس المفهوم "
                        "تعنيان تمثيلًا مزدوجًا هشًّا",
                        "وحّد تمثيل الحالة (مفاتيح لاتينية) وترجم عند العرض فقط",
                    )
                    return

        if a is None or b is None:
            continue
        if _letters_mismatch(a, b):
            _fire_compare(
                node,
                source,
                filename,
                findings,
                "مقارنة سلسلة بحروف عربية بسلسلة بحروف لاتينية فقط — لا يمكن أن تتطابق أبدًا",
                "وحّد لغة القيمتين، أو قارن بمفاتيح لاتينية ثابتة داخل الشيفرة",
            )
            return
        if _digits_mismatch(a, b):
            _fire_compare(
                node,
                source,
                filename,
                findings,
                "مقارنة أرقام عربية-هندية بأرقام غربية — طبّع الأرقام أولًا",
                "مرّر القيمتين على تطبيع الأرقام (مثل zyko_pii_ar.normalize_digits) قبل المقارنة",
            )
            return


def _fire_compare(
    node: ast.Compare,
    source: str,
    filename: str,
    findings: list[Finding],
    message: str,
    suggestion: str,
) -> None:
    offset = _node_offset(source, node)
    line, col = line_col_of(source, offset)
    findings.append(
        Finding(
            "RTL-PY-001",
            "error",
            message,
            filename,
            line,
            col,
            excerpt_of(source, offset),
            suggestion,
        )
    )


def _check_identifier(
    name: str,
    node: ast.AST,
    source: str,
    filename: str,
    findings: list[Finding],
    seen: set[str],
) -> None:
    if name in seen:
        return
    issue = _identifier_issue(name)
    if issue is None:
        return
    seen.add(name)
    offset = _node_offset(source, node)
    line, col = line_col_of(source, offset)
    findings.append(
        Finding(
            "RTL-PY-004",
            "warning",
            f"المعرّف «{name}» يحوي {issue} — يصعب البحث عنه ويظهر مبعثرًا في المحررات",
            filename,
            line,
            col,
            excerpt_of(source, offset),
            "استخدم أسماء لاتينية للمعرّفات، واحتفظ بالعربية للرسائل والتعليقات",
        )
    )


def _add_mixed_finding(source: str, node: ast.AST, filename: str, findings: list[Finding]) -> None:
    offset = _node_offset(source, node)
    line, col = line_col_of(source, offset)
    findings.append(
        Finding(
            "RTL-PY-002",
            "info",
            "سلسلة رسائل تخلط العربية باللاتينية بلا محارف اتجاه — قد تُعرض مبعثرة في الطرفيات",
            filename,
            line,
            col,
            excerpt_of(source, offset),
            "أضف علامات الاتجاه (LRM/RLM) أو افصل المقاطع اللاتينية في وسيط منفصل",
        )
    )
